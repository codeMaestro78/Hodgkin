"""Resolve migration targets with test-environment isolation by default."""


def migration_database_url(
    *,
    app_env: str,
    explicit_admin_url: str | None,
    settings_admin_url: str | None,
    private_admin_url: str | None,
    application_url: str,
) -> str:
    """Never let a private hosted migration URL override a disposable test URL."""
    if explicit_admin_url:
        return explicit_admin_url
    if settings_admin_url:
        return settings_admin_url
    if app_env == "test":
        return application_url
    return private_admin_url or application_url
