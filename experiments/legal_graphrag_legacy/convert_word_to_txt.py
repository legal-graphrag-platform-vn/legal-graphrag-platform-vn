import os
import glob

def convert_doc_to_txt(input_dir, output_dir):
    """
    Chuyển đổi tất cả các file .doc và .docx trong input_dir sang .txt (UTF-8) và lưu vào output_dir.
    Yêu cầu: Máy tính cài sẵn Microsoft Word và thư viện pywin32.
    """
    try:
        import win32com.client
    except ImportError:
        print("Lỗi: Không tìm thấy thư viện 'pywin32'.")
        print("Vui lòng chạy lệnh: pip install pywin32")
        return

    # Tạo thư mục đầu ra nếu chưa tồn tại
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Tìm tất cả các file .doc và .docx
    doc_files = glob.glob(os.path.join(input_dir, '*.doc')) + glob.glob(os.path.join(input_dir, '*.docx'))
    
    if not doc_files:
        print(f"Không tìm thấy file .doc hay .docx nào trong thư mục: {input_dir}")
        return

    print(f"Tìm thấy {len(doc_files)} file Word. Bắt đầu chuyển đổi...")

    try:
        # Khởi động MS Word ngầm
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
    except Exception as e:
        print(f"Lỗi khi khởi động MS Word. Hãy đảm bảo bạn đã cài MS Word trên máy. Chi tiết lỗi: {e}")
        return

    for file_path in doc_files:
        try:
            # MS Word COM yêu cầu đường dẫn tuyệt đối (absolute path)
            abs_input_path = os.path.abspath(file_path)
            
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            output_path = os.path.abspath(os.path.join(output_dir, f"{base_name}.txt"))

            print(f"Đang xử lý: {base_name}...")
            
            # Mở file
            doc = word.Documents.Open(abs_input_path)
            
            # Lấy toàn bộ text và tự tay ghi bằng Python để đảm bảo chuẩn UTF-8 thuần
            text_content = doc.Content.Text
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text_content)
            
            # Đóng file không lưu thay đổi bản gốc
            doc.Close(False)
                
            print(f"Đã chuyển đổi thành công: {base_name}.txt")
            
        except Exception as e:
            print(f"Lỗi khi xử lý file {file_path}: {e}")

    # Tắt ứng dụng Word
    word.Quit()

if __name__ == "__main__":
    # Nguồn: File doc của bạn
    INPUT_FOLDER = r"D:\Final_Sem\doc"
    # Đích: Thư mục input của GraphRAG
    OUTPUT_FOLDER = r"D:\Final_Sem\GraphRAG\input"
    
    convert_doc_to_txt(INPUT_FOLDER, OUTPUT_FOLDER)
    print("\nHoàn tất quá trình chuyển đổi! Các file .txt (UTF-8) đã sẵn sàng trong thư mục 'input'.")
