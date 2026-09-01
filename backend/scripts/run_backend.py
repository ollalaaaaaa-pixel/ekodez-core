import uvicorn


def create_config() -> uvicorn.Config:
    return uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        proxy_headers=False,
    )


def main() -> None:
    uvicorn.Server(create_config()).run()


if __name__ == "__main__":
    main()
