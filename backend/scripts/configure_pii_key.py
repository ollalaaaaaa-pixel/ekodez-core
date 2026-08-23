from pathlib import Path

from cryptography.fernet import Fernet


def main() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    lines = (
        env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    )
    if any(
        line.startswith("PII_FERNET_KEY=") and line.partition("=")[2].strip()
        for line in lines
    ):
        print("PII_FERNET_KEY already configured")
        return
    lines = [line for line in lines if not line.startswith("PII_FERNET_KEY=")]
    lines.append(f"PII_FERNET_KEY={Fernet.generate_key().decode('ascii')}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("PII_FERNET_KEY generated and stored in backend/.env")


if __name__ == "__main__":
    main()
