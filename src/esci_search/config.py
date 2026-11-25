

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ESCI_", env_file=".env", env_file_encoding="utf-8",
        extra="forbid", frozen=True,
    )