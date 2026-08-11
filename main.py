"""Entrypoint for the web-kernel and CLI tools (imperal validate/build).
Sets up sys.path, purges stale module cache, then imports ext/chat and all
handler modules so their decorators register on the same Extension instance."""
import os
import sys

_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
if _EXT_DIR not in sys.path:
    sys.path.insert(0, _EXT_DIR)

# Purge stale cached modules so a fresh load always registers decorators correctly
# (the validator may run multiple extensions in the same process).
_LOCAL = ("app", "handlers_connect", "handlers_read", "handlers_woocommerce",
          "handlers_woocommerce_catalog", "handlers_woocommerce_operations",
          "handlers_woocommerce_finance", "handlers_woocommerce_order_edit",
          "handlers_seo", "handlers_builders", "handlers_posts", "handlers_media",
          "handlers_taxonomy", "handlers_links", "handlers_users", "handlers_menus", "handlers_post_lifecycle", "handlers_reviews", "handlers_site_settings", "handlers_redirects", "handlers_meta", "handlers_cache_cron", "handlers_database", "handlers_rest_api", "handlers_security", "handlers_deploy", "handlers_logs", "handlers_cpt_taxonomy", "handlers_blocks", "handlers_webhooks", "handlers_action_scheduler", "handlers_rewrite", "handlers_import_export", "handlers_integrity", "handlers_mail", "handlers_core_site_health", "handlers_sessions", "skeleton", "panels", "models", "storage", "wp_client", "wp_cli", "gutenberg")
for _mod in _LOCAL:
    sys.modules.pop(_mod, None)

from app import ext, chat  # noqa: E402,F401
import handlers_connect  # noqa: E402,F401
import handlers_read  # noqa: E402,F401
import handlers_woocommerce  # noqa: E402,F401
import handlers_woocommerce_catalog  # noqa: E402,F401
import handlers_woocommerce_operations  # noqa: E402,F401
import handlers_woocommerce_finance  # noqa: E402,F401
import handlers_woocommerce_order_edit  # noqa: E402,F401
import handlers_seo  # noqa: E402,F401
import handlers_builders  # noqa: E402,F401
import handlers_posts  # noqa: E402,F401
import handlers_media  # noqa: E402,F401
import handlers_taxonomy  # noqa: E402,F401
import handlers_links  # noqa: E402,F401
import handlers_users  # noqa: E402,F401
import handlers_menus  # noqa: E402,F401
import handlers_post_lifecycle  # noqa: E402,F401
import handlers_reviews  # noqa: E402,F401
import handlers_site_settings  # noqa: E402,F401
import handlers_redirects  # noqa: E402,F401
import handlers_maintenance  # noqa: E402,F401
import handlers_rankmath  # noqa: E402,F401
import handlers_indexnow  # noqa: E402,F401
import handlers_llmstxt  # noqa: E402,F401
import handlers_meta  # noqa: E402,F401
import handlers_cache_cron  # noqa: E402,F401
import handlers_database  # noqa: E402,F401
import handlers_rest_api  # noqa: E402,F401
import handlers_security  # noqa: E402,F401
import handlers_deploy  # noqa: E402,F401
import handlers_logs  # noqa: E402,F401
import handlers_cpt_taxonomy  # noqa: E402,F401
import handlers_blocks  # noqa: E402,F401
import handlers_webhooks  # noqa: E402,F401
import handlers_action_scheduler  # noqa: E402,F401
import handlers_rewrite  # noqa: E402,F401
import handlers_import_export  # noqa: E402,F401
import handlers_integrity  # noqa: E402,F401
import handlers_mail  # noqa: E402,F401
import handlers_core_site_health  # noqa: E402,F401
import handlers_sessions  # noqa: E402,F401
import skeleton  # noqa: E402,F401
import panels  # noqa: E402,F401
