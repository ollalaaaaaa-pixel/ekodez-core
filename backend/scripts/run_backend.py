import uvicorn


def create_config() -> uvicorn.Config:
    return uvicorn.Config(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        proxy_headers=False,
    )


def main() -> None:
    uvicorn.Server(create_config()).run()


if __name__ == "__main__":
    main()
