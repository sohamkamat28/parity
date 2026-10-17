import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parity.embedding import Embedder
model=Embedder("minilm")
print("Model loaded:",model.signature)
print("Vector dimensions:",len(model.encode("Parity stores versioned evidence.")))
