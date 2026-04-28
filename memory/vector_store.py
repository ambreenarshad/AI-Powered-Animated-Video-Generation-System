#memory/vector_store.py
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
import os

DB_DIR = "memory_db"

embedding = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

vectorstore = Chroma(
    persist_directory=DB_DIR,
    embedding_function=embedding
)

def store_memory(text, metadata):
    vectorstore.add_texts([text], metadatas=[metadata])
    # NOTE: .persist() was removed in langchain-chroma >= 0.1.0
    # Chroma now auto-persists when persist_directory is set

def query_memory(query):
    return vectorstore.similarity_search(query, k=3)