"""Shared anti-detection helpers for Playwright-based crawlers."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_STEALTH_JS = """
(() => {
    // Hide webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Realistic plugins array (Chrome on Linux)
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' },
        ],
    });

    // Languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
    });

    // Chrome runtime stub
    if (!window.chrome) {
        window.chrome = { runtime: {}, loadTimes: () => ({}), csi: () => ({}) };
    }

    // Permissions.query override (notifications)
    const origQuery = window.navigator.permissions?.query?.bind(
        window.navigator.permissions,
    );
    if (origQuery) {
        window.navigator.permissions.query = (params) =>
            params.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : origQuery(params);
    }
})();
"""


def stealth_context_options() -> dict[str, Any]:
    return {
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "java_script_enabled": True,
    }


async def inject_stealth(page: Any) -> None:
    """Inject stealth scripts into a Playwright page before navigation."""
    try:
        await page.add_init_script(_STEALTH_JS)
    except Exception:
        log.debug("Failed to inject stealth script", exc_info=True)
