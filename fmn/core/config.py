from functools import cache

from pydantic import BaseModel, BaseSettings, root_validator, stricturl

settings_file = None  # will be set from CLI


class SQLAlchemyModel(BaseModel):
    url: stricturl(tld_required=False, host_required=False) = "sqlite:///:memory:"

    class Config:
        extra = "allow"


class DBModel(BaseModel):
    sqlalchemy: SQLAlchemyModel = SQLAlchemyModel()


class Settings(BaseSettings):
    cors_origins: str = "https://notifications.fedoraproject.org"
    oidc_provider_url: str = "https://id.fedoraproject.org/openidc"
    oidc_conf_endpoint: str = "/.well-known/openid-configuration"
    oidc_token_info_endpoint: str = "/TokenInfo"
    oidc_client_id: str = "0123456789abcdef0123456789abcdef"
    oidc_client_secret: str = "0123456789abcdef0123456789abcdef"
    fasjson_url: str = "https://fasjson.fedoraproject.org"

    id_cache_gc_interval: int = 300

    database: DBModel = DBModel()

    class Config:
        env_file = "fmn.cfg"
        env_nested_delimiter = "__"

    @root_validator
    def compute_compound_fields(cls, values) -> dict:
        values["oidc_conf_url"] = (
            values["oidc_provider_url"].rstrip("/") + "/" + values["oidc_conf_endpoint"].lstrip("/")
        )
        values["oidc_token_info_url"] = (
            values["oidc_provider_url"].rstrip("/")
            + "/"
            + values["oidc_token_info_endpoint"].lstrip("/")
        )
        return values


@cache
def get_settings() -> Settings:
    return Settings(_env_file=settings_file)