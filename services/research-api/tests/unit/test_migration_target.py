from research_api.db.migrations.target import migration_database_url


def test_test_environment_ignores_private_hosted_migration_url():
    assert (
        migration_database_url(
            app_env="test",
            explicit_admin_url=None,
            settings_admin_url=None,
            private_admin_url="postgresql://hosted.invalid/postgres",
            application_url="postgresql://localhost/disposable",
        )
        == "postgresql://localhost/disposable"
    )


def test_explicit_admin_url_wins_and_non_test_can_use_private_migration_url():
    assert (
        migration_database_url(
            app_env="test",
            explicit_admin_url="postgresql://localhost/explicit",
            settings_admin_url=None,
            private_admin_url="postgresql://hosted.invalid/postgres",
            application_url="postgresql://localhost/application",
        )
        == "postgresql://localhost/explicit"
    )
    assert (
        migration_database_url(
            app_env="production",
            explicit_admin_url=None,
            settings_admin_url=None,
            private_admin_url="postgresql://hosted.invalid/postgres",
            application_url="postgresql://localhost/application",
        )
        == "postgresql://hosted.invalid/postgres"
    )
