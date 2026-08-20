import sys
from core.router import QueryRouter
from core.retriever import GraphRetriever
from core.generator import AnswerGenerator
from core.memory import MemoryManager

sys.stdout.reconfigure(encoding='utf-8')

# 🚀 Khởi tạo các module (Singleton) một lần duy nhất ngoài vòng lặp
router = QueryRouter()
retriever = GraphRetriever()
generator = AnswerGenerator()
memory = MemoryManager(max_turns=3) # Ghi nhớ tối đa 3 vòng chat gần nhất

def run_pipeline(user_query: str):
    print("="*80)
    print(f"🚀 BẮT ĐẦU XỬ LÝ CÂU HỎI: {user_query}")
    print("="*80)
    
    # Bước 0: Viết lại câu hỏi (Query Reformulation)
    standalone_query = memory.contextualize_query(user_query)
    if standalone_query != user_query:
        print(f"👉 [Memory] Câu hỏi đã được viết lại: {standalone_query}")
        print("-" * 40)
    
    # Bước 1: Router
    intent, temporal = router.analyze(standalone_query)
    print(f"👉 [Router] Intent phân loại: {intent}")
    print(f"👉 [Router] Temporal: {temporal}")
    print("-" * 40)
    
    # Bước 2 & 3: Retriever
    anchor_nodes = retriever.find_entry_points(standalone_query)
    print(f"👉 [Retriever] Điểm neo tìm thấy (Node IDs): {anchor_nodes}")
    
    context = retriever.traverse_graph(anchor_nodes, intent, temporal)
    print(f"👉 [Retriever] Đã gom xong Context đồ thị.")
    print("-" * 40)
    
    # Bước 4: Generator
    # Bơm Context, Câu hỏi độc lập và Lịch sử trò chuyện vào LLM
    answer = generator.generate(standalone_query, context, chat_history=memory.get_history_messages())
    
    # Bước 5: Cập nhật Trí nhớ (Memory)
    memory.add_interaction(user_query, answer)
    
    print("\n" + "="*80)
    print("🤖 CÂU TRẢ LỜI CỦA GRAPH-RAG:")
    print("="*80)
    print(answer)
    print("="*80)

if __name__ == "__main__":
    print("="*80)
    print("🌟 CHÀO MỪNG ĐẾN VỚI TRỢ LÝ PHÁP LÝ AI (Hỗ trợ Hội thoại) 🌟")
    print("="*80)
    
    while True:
        try:
            user_input = input("\n👤 Mời bạn nhập câu hỏi (hoặc gõ 'exit' để thoát): ")
            if user_input.strip().lower() in ['exit', 'quit', 'q']:
                print("👋 Tạm biệt!")
                break
                
            if not user_input.strip():
                continue
                
            run_pipeline(user_input.strip())
            
        except KeyboardInterrupt:
            print("\n👋 Tạm biệt!")
            break
