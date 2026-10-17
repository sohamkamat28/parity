import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)
# Keep downloaded runtime assets with this installation, outside release archives.
CACHE = Path(os.getenv("PARITY_CACHE_DIR", ROOT / ".cache")).resolve()
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(CACHE / "ms-playwright"))
os.environ.setdefault("PARITY_MODEL_CACHE", str(CACHE / "models"))
os.environ.setdefault("HF_HOME", str(CACHE / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
DATA = Path(os.getenv("PARITY_DATA_DIR", ROOT / "data")).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///" + str(DATA / "parity.db"))
DEMO_ORIGIN = os.getenv("DEMO_ORIGIN", "http://127.0.0.1:8080").rstrip("/")
EMBEDDER = os.getenv("PARITY_EMBEDDER", "minilm")
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = os.getenv("PARITY_MODEL_REVISION", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41")
ADMIN_TOKEN = os.getenv("PARITY_ADMIN_TOKEN", "")
LEASE_SECONDS = 120
CHAT_MODEL = os.getenv("PARITY_CHAT_MODEL", "gpt-5.4-mini-2026-03-17")
CHAT_PROVIDER = os.getenv('PARITY_CHAT_PROVIDER', 'local')
LOCAL_CHAT_MODEL = 'qwen2.5-1.5b-instruct-q4_k_m'
LOCAL_CHAT_PORT = int(os.getenv('PARITY_LOCAL_CHAT_PORT','8091'))
API_PORT = int(os.getenv("PARITY_PORT", "8000"))
EMBEDDING_PORT = int(os.getenv('PARITY_EMBEDDING_PORT', '8092'))
