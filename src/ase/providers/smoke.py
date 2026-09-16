from .factory import build_chat_model
from .settings import ModelSettings


def main() -> None:
    settings = (
        ModelSettings.from_environment()
    )

    model = build_chat_model(
        settings
    )

    response = model.invoke(
        "Reply with exactly MODEL_OK."
    )

    print(
        f"provider={settings.provider}"
    )
    print(
        f"model={settings.model}"
    )
    print(response.content)


if __name__ == "__main__":
    main()
