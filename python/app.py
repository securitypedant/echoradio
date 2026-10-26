"""WSGI entry point: ``gunicorn app:app`` in production, ``python app.py`` in development."""
import os

from mods import create_app

app = create_app()

if __name__ == "__main__":
    if os.environ.get("FLASK_ENV") == "development":
        try:
            import debugpy

            debugpy.listen(("0.0.0.0", 5678))
            if os.environ.get("DEBUGPY_WAIT") == "1":
                print("Waiting for debugger to attach on :5678 ...", flush=True)
                debugpy.wait_for_client()
        except ImportError:
            pass
    app.run(host="127.0.0.1", port=5000, debug=app.config.get("DEBUG", False), use_reloader=False, threaded=True)
