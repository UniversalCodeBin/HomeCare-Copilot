# Product Feedback: HomeCare Copilot

### Model Context Protocol (MCP) and Python SDK

- **What we used it for:** Implementing a robust, structured server-side communication layer for appliance diagnostics and safe purchasing actions, utilizing Streamable HTTP for transport.
- **What worked well:** The protocol's strong definition of tools with structured input/output schemas allowed us to build predictable, deterministic agent behavior. The ability to return `spoken_summary` for voice TTS alongside structured `details` for web UIs is an excellent architectural pattern for assistant development.
- **What needs improvement:** While the SDK is powerful, discovery mechanisms in the Streamable HTTP transport feel slightly less ergonomic than native SSE.
- **Onboarding experience:** The documentation is clear and provided a solid foundation.
- **Would we build with it again?** Yes, because it elevates the standard of reliability for agent-to-tool communication.
- **Evidence or example:** `server/tools.py` defines the 8 core tools, demonstrating clean separation of agent logic from tool execution.

### FastAPI

- **What we used it for:** Serving both the Simulated Alexa+ Host and the MCP Server (via `streamable_http_app`).
- **What worked well:** Excellent performance, intuitive routing, and built-in support for asynchronous request handling.
- **What needs improvement:** None for this use case.
- **Onboarding experience:** Extremely smooth; standard for Python web services.
- **Would we build with it again?** Yes.

### Amazon AWS Services

- **What we used it for:** No AWS service was integrated into the current implementation. The project is a simulated local environment.

### Simulated Alexa+ Host / Web Speech API

- **What we used it for:** Providing the user interface and voice-interaction layer for the copilot.
- **What worked well:** The Web Speech API provides a low-friction way to add TTS features without external paid APIs.
- **What needs improvement:** Browser support and voice naturalness vary across platforms.
- **Onboarding experience:** Straightforward, though UI/UX polish requires custom CSS and JS management.
- **Would we build with it again?** Yes, for rapid prototyping and local demos.

### Pytest / Evaluation Suite

- **What we used it for:** Automating the validation of appliance state, safety policies, order purchasing, and live MCP transport.
- **What worked well:** `pytest-asyncio` made testing asynchronous tool calls trivial and fast.
- **What needs improvement:** None.
- **Onboarding experience:** Excellent.
- **Would we build with it again?** Yes.
