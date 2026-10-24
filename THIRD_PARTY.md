# Dependencies and attribution

Project source and generated model/visuals use the repository MIT license.
Dependencies retain their own licenses/notices and are not vendored here.

| Dependency | Role | Upstream |
|---|---|---|
| Python | Numerical core | https://www.python.org/ |
| FastAPI, Starlette, Pydantic, Uvicorn | Local API/ASGI | https://fastapi.tiangolo.com/ |
| React / React DOM | Console | https://react.dev/ |
| TypeScript / Vite | Frontend checking/build | https://www.typescriptlang.org/ · https://vite.dev/ |
| Matplotlib, NumPy, Pillow | Exact charts and trace animation | https://matplotlib.org/ · https://numpy.org/ · https://python-pillow.github.io/ |
| Playwright | Standalone browser script | https://playwright.dev/ |
| httpx / pytest | Testing tools | https://www.python-httpx.org/ · https://pytest.org/ |

Exact versions/integrities are in requirements-web.lock and frontend/package-lock.json.
CI uses official GitHub Actions pinned to verified commits. The numerical models
are project implementations of established algorithms, not novelty claims.
No third-party training data or pretrained model is included.

Images are actual app screenshots, plots of saved data, or renderings of recorded
simulation positions. No external fonts/image assets are required by the app.
Substantial Codex assistance is disclosed in the README and reviewer guide.
