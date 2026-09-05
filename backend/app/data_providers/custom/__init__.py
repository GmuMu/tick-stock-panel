"""Custom data source extension points."""
from app.data_providers.base import ProviderRoute
from app.data_providers.custom.loader import (
    create_provider,
    data_sources_dir,
    delete_config,
    errors,
    get_config_dict,
    get_provider,
    install_plugin,
    is_builtin,
    is_custom_provider,
    list_plugins,
    list_sources,
    load_all,
    names,
    plugin_manifest,
    probe_plugin_key,
    provider_has_dataset,
    save_config,
    uninstall_plugin,
)
from app.data_providers.custom.loader import resolve_route as _resolve_route

__all__ = [
    "create_provider",
    "data_sources_dir",
    "delete_config",
    "errors",
    "get_config_dict",
    "get_provider",
    "install_plugin",
    "is_builtin",
    "is_custom_provider",
    "list_plugins",
    "list_sources",
    "load_all",
    "names",
    "plugin_manifest",
    "probe_plugin_key",
    "provider_has_dataset",
    "resolve_route",
    "save_config",
    "uninstall_plugin",
]


def resolve_route(name: str | None, dataset: str) -> ProviderRoute:
    """Resolve a route while keeping the public registry hooks patchable.

    The package-level wrapper is the service boundary. Passing the exported
    hooks through keeps tests and optional integrations able to isolate the
    provider registry without reaching into loader implementation globals.
    """
    return _resolve_route(
        name,
        dataset,
        has_dataset=provider_has_dataset,
        provider_getter=get_provider,
    )
