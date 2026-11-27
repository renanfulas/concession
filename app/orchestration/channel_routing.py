"""Shared domain routing + sticky memory for conversational channels.

Both the Meta WhatsApp transport and the temporary Hermes chat transport answer
more than one domain (support and sales) on a single number, and the web chat
(``/web/chat``) serves the same domains on one endpoint. This module holds the
channel-agnostic glue so the routing/stickiness rules live in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.domain_engine.loader import DomainLoader
from app.orchestration.domain_router import DomainRouter
from app.orchestration.session_domain_store import SessionDomainStore


@dataclass(frozen=True)
class RouteResolution:
    domain: str | None
    show_menu: bool = False
    selected: bool = False
    # True when the user explicitly asked to switch/restart ("menu", "trocar"):
    # the fallback should go straight to the clarification question instead of
    # re-introducing the company.
    reset: bool = False


@dataclass(frozen=True)
class ChannelTurn:
    """What a channel should do with one inbound message.

    ``routing_text`` set means "reply with this text and do not call the brain":
    the greeting/clarification for an unrouted turn (``routing_menu``) or the
    domain welcome for a bare menu choice such as "2" (``routing_selected``).
    Otherwise ``domain`` is the domain that answers the message.
    """

    domain: str | None
    routing_text: str | None = None
    routing_status: str | None = None


def build_domain_router(
    settings: Settings,
    domain_loader: DomainLoader,
    *,
    enabled: bool | None = None,
) -> DomainRouter | None:
    """Build the router from settings, or None when routing is disabled/single.

    ``enabled`` lets a channel use its own switch (the web chat passes
    ``ENABLE_WEB_DOMAIN_ROUTER``); it defaults to the WhatsApp switch.
    """
    if enabled is None:
        enabled = settings.enable_whatsapp_domain_router
    if not enabled:
        return None
    configs = [
        config
        for name in settings.whatsapp_router_domain_list
        if (config := domain_loader.load(name)) is not None
    ]
    if len(configs) <= 1:
        return None
    return DomainRouter.from_domain_configs(
        configs,
        default_domain=settings.default_domain,
    )


def resolve_sticky_domain(
    *,
    router: DomainRouter | None,
    store: SessionDomainStore | None,
    default_domain: str,
    text: str,
    session_id: str,
) -> RouteResolution:
    """Decide how to handle an inbound message.

    Stickiness: a menu selection or keyword match (re)binds the session to that
    domain; a generic follow-up keeps the bound domain; a reset trigger drops the
    binding and shows the menu. A bare menu selection (e.g. "2") must NOT be fed to
    the brain — it is only a chooser — so it is flagged ``selected`` for a welcome.
    """
    if router is None:
        return RouteResolution(domain=default_domain)

    if store is not None and router.is_reset(text):
        store.clear(session_id)
        return RouteResolution(domain=None, show_menu=True, reset=True)

    decision = router.route(text)
    intentful = {"menu_selection", "keyword_match", "single_domain"}
    if decision.domain is not None and decision.reason in intentful:
        if store is not None:
            store.set(session_id, decision.domain)
        return RouteResolution(
            domain=decision.domain,
            selected=decision.reason == "menu_selection",
        )

    if store is not None:
        sticky = store.get(session_id)
        if sticky is not None:
            return RouteResolution(domain=sticky)

    if decision.domain is None:
        return RouteResolution(domain=None, show_menu=True)
    return RouteResolution(domain=decision.domain)


def route_channel_turn(
    *,
    router: DomainRouter | None,
    store: SessionDomainStore | None,
    last_out_store: SessionDomainStore | None,
    default_domain: str,
    text: str,
    session_id: str,
) -> ChannelTurn:
    """Full routing decision for a request/response channel (the web chat).

    Same rules as the WhatsApp transports: sticky domain per session, reset
    trigger, greeting then clarification for unrouted turns, welcome for a bare
    menu choice. ``session_id`` must already be sanitized (a digest), because it
    is the key of the sticky and last-outbound stores.
    """
    resolution = resolve_sticky_domain(
        router=router,
        store=store,
        default_domain=default_domain,
        text=text,
        session_id=session_id,
    )
    if router is None:
        return ChannelTurn(domain=resolution.domain)
    if resolution.show_menu or resolution.domain is None:
        last_outbound = (
            last_out_store.get(session_id) if last_out_store is not None else None
        )
        routing_text = fallback_routing_text(
            router,
            last_outbound=last_outbound,
            reset=resolution.reset,
        )
        if last_out_store is not None:
            last_out_store.set(session_id, routing_text)
        return ChannelTurn(
            domain=None,
            routing_text=routing_text,
            routing_status="routing_menu",
        )
    if resolution.selected:
        return ChannelTurn(
            domain=resolution.domain,
            routing_text=router.welcome_text(resolution.domain),
            routing_status="routing_selected",
        )
    return ChannelTurn(domain=resolution.domain)


def fallback_routing_text(
    router: DomainRouter,
    *,
    last_outbound: str | None,
    reset: bool = False,
) -> str:
    """Pick the customer-facing text for an unrouted (``show_menu``) turn.

    First contact gets the institutional greeting. When the greeting or the
    clarification was the last thing sent (the reply is still ambiguous), or the
    user explicitly asked to switch (reset), send the clarification question so
    the conversation moves forward instead of repeating the company intro.
    """
    if reset:
        return router.clarification_text()
    if last_outbound in (router.greeting_text(), router.clarification_text()):
        return router.clarification_text()
    return router.greeting_text()
