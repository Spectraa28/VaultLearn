from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers  import CrossEncoder
import chromadb
from rag.chunker import chunk_page

embedding_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
client = chromadb.PersistentClient(path="./chroma_db")

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
    
    embeddings = embedding_model.embed_documents(documents)
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
    
    query_embedding = embedding_model.embed_query(query)
    
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"module_number":module_number},
        include=["documents", "metadatas","distances"]
    )
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
    
    scores = reranker.predict(pairs)
    
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