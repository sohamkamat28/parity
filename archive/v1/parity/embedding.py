import os, math, re, hashlib
from collections import Counter
from . import config

STOPWORDS=set("a an the is are was were be been being do does did how what when where which who why tell me my your our their its it this that these those of for to in on at by with and or as from about can could would should will please give have has had need i we you they he she".split())

def tokens(text):
    return re.findall(r"\b[\w-]+\b",text.lower())

class Embedder:
    def __init__(self,mode=None):
        self.mode=mode or config.EMBEDDER
        self.model=None
        if self.mode=="minilm":
            from sentence_transformers import SentenceTransformer
            self.model=SentenceTransformer(config.MODEL,revision=config.MODEL_REVISION,
                cache_folder=os.getenv("PARITY_MODEL_CACHE"),device="cpu",
                local_files_only=os.getenv("PARITY_OFFLINE","1")!="0")
            self.signature="minilm:"+config.MODEL_REVISION+":mean:normalized:384:v1"
        elif self.mode=="lexical":
            self.signature="lexical-hash:sha256:384:normalized:v1"
        else: raise ValueError("PARITY_EMBEDDER must be lexical or minilm")

    def split(self,text,prefix):
        if self.model:
            tokenizer=self.model.tokenizer
            # Split words, checking the entire input every time; no truncation.
            out=[];buf=[]
            for word in text.split():
                trial=" ".join(buf+[word])
                if len(tokenizer.encode(prefix+trial))>256:
                    if not buf: raise ValueError("Heading or token exceeds embedding limit")
                    out.append(" ".join(buf));buf=[word]
                    if len(tokenizer.encode(prefix+word))>256: raise ValueError("Oversized embedding input")
                else: buf.append(word)
            if buf:out.append(" ".join(buf))
            return out
        words=text.split()
        return [" ".join(words[i:i+120]) for i in range(0,len(words),120)]

    def encode(self,text):
        if self.model:
            if len(self.model.tokenizer.encode(text))>256:
                raise ValueError("Embedding input exceeds token limit")
            return self.model.encode(text,normalize_embeddings=True).tolist()
        # Explicit lexical feature hashing, not a semantic model or learned embedding.
        vec=[0.0]*384
        for token,count in Counter(tokens(text)).items():
            h=int.from_bytes(hashlib.sha256(token.encode()).digest()[:8],"big")
            vec[h%384]+=1+math.log(count)
        norm=math.sqrt(sum(v*v for v in vec)) or 1
        return [v/norm for v in vec]

def cosine(a,b):
    return float(sum(x*y for x,y in zip(a,b)))
