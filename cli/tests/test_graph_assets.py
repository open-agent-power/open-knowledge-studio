"""The learning graph must ship and serve its same-origin runtime."""
from knowledge_studio.mail_web import FILES, ROOT


def test_learning_graph_assets_are_registered_and_present():
    paths = (
        "/studio/graph-pixi.js", "/studio/graph-camera.js",
        "/studio/graph-controls.js", "/studio/graph-layout.js",
        "/studio/graph-renderer.js", "/vendor/graph-engine/pixi.min.js",
        "/vendor/graph-engine/layout.worker.js", "/vendor/graph-engine/edge-mesh.js",
        "/vendor/graph-engine/position-smoothing.js",
    )
    for path in paths:
        relative_path, content_type = FILES[path]
        assert content_type == "text/javascript"
        assert (ROOT / relative_path).is_file()
