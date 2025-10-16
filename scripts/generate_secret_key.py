
import secrets
import string

def generate_secret_key(length: int = 64) -> str:
    return secrets.token_urlsafe(length)

def main():
    key = generate_secret_key()
    print("Generated SECRET_KEY:")
    print(f"SECRET_KEY={key}")


if __name__ == "__main__":
    main()
