from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers  import CrossEncoder
import chromadb
from rag.chunker import chunk_page
from functools import lru_cache
from time import perf_counter
from observability import event

client = chromadb.PersistentClient(path="./chroma_db")

@lru_cache(maxsize=1)
def get_embedding_model():
    return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

@lru_cache(maxsize=1)
def get_reranker():
    return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

def build_collection(chunks: list[dict], collection_name:str):
    if not chunks:
        raise ValueError("Cannot build collection from empty chunks")
    
    documents = [
        chunk["text"]
        for chunk in chunks 
    ]
    
    metadata = [
        {
            key : value 
            for key, value in chunk.items()
            if key != "text"
        }
        for chunk in chunks 
    ]
    
    ids = [
        f"{collection_name}_{i}"
        for i in range(len(chunks))
    ]
    
    started = perf_counter()
    embeddings = get_embedding_model().embed_documents(documents)
    event("embedding.completed", duration_ms=(perf_counter() - started) * 1000, details={"documents": len(documents)})
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    
    collection = client.create_collection(
        name=collection_name
    )
    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadata
    )
    return collection

def dense_retrieve(collection , query:str,module_number:int,top_k:int =5) -> list[dict]:
    
    started = perf_counter()
    query_embedding = get_embedding_model().embed_query(query)
    
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"module_number":module_number},
        include=["documents", "metadatas","distances"]
    )
    event("vector_query.completed", duration_ms=(perf_counter() - started) * 1000, details={"module_number": module_number, "top_k": top_k})
    retrieved = []
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]
    
    for document ,metadata, distance in zip(documents,metadatas,distances):
        retrieved.append({
            "text":document,
            "metadata":metadata,
            "score": 1/(1+distance),
            "distance":distance
        })
        
    return retrieved

def rerank(query:str,candidates:list[dict]) -> list[dict]:
    if not candidates:
        return []
    
    pairs =[
        [query,candidate["text"]]
        for candidate in candidates
    ]
    
    started = perf_counter()
    scores = get_reranker().predict(pairs)
    event("rerank.completed", duration_ms=(perf_counter() - started) * 1000, details={"candidates": len(candidates)})
    
    reranked = []
    
    for candidate , score in zip(candidates,scores):
        new_candidate = candidate.copy()
        new_candidate["rerank_score"] = float(score)
        reranked.append(new_candidate)
        
    reranked.sort(
        key= lambda item: item["rerank_score"],
        reverse=True
    )
    
    return reranked


def retrieve(collection,query:str,module_number:int,top_k:int=5) -> list[dict]:
    
    candidates = dense_retrieve(
        collection=collection,
        query=query,
        module_number=module_number,
        top_k=top_k
    )
    
    final_result = rerank(
        query=query,
        candidates=candidates
    )
    
    return final_result
