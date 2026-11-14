import os

import uvicorn

from .brand import PRODUCT_NAME, TAGLINE


def main():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"{PRODUCT_NAME} on http://{host}:{port}")
    print(TAGLINE)
    print("Rule-based and offline unless LLM_* or JIRA_* variables are set.")
    uvicorn.run("verireq.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
