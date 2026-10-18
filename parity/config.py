import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)
def installation_path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()
# Keep downloaded runtime assets with this installation, outside release archives.
CACHE = installation_path(os.getenv("PARITY_CACHE_DIR", ROOT / ".cache"))
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(CACHE / "ms-playwright"))
os.environ.setdefault("PARITY_MODEL_CACHE", str(CACHE / "models"))
os.environ.setdefault("HF_HOME", str(CACHE / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
DATA = installation_path(os.getenv("PARITY_DATA_DIR", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
from urllib.parse import quote
PROFILE = os.getenv('PARITY_PROFILE', 'postgresql')
DATABASE_URL = os.getenv("DATABASE_URL") or ('sqlite:///'+str(DATA/'parity.db') if PROFILE == 'sqlite' else
    'postgresql+psycopg://parity:'+quote(os.getenv('PARITY_DB_PASSWORD',''),safe='')+'@127.0.0.1:'+os.getenv('PARITY_DB_PORT','5432')+'/parity')
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
