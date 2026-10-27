import uvicorn
from loguru import logger

from app.config import config
from app.services.rick_security_network import safe_api_bind_host

if __name__ == "__main__":
    logger.info(
        "start server, docs: http://127.0.0.1:" + str(config.listen_port) + "/docs"
    )
    # FFmpeg 探测已经移到 app/services/task.py 的共享任务流水线里，这样
    # API、CLI 和 WebUI 三条路径都能统一覆盖，这里不再单独检查。
    bind_host = safe_api_bind_host(config.listen_host, config.app.get("api_key", ""))
    if bind_host != config.listen_host:
        logger.warning(
            "API without an access key is restricted to loopback; "
            "configure authentication for network access."
        )
    uvicorn.run(
        app="app.asgi:app",
        host=bind_host,
        port=config.listen_port,
        reload=config.reload_debug,
        log_level="warning",
    )
