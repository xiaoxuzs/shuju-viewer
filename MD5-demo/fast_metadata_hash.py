import os
import hashlib
import time
import json
from typing import Tuple

def calculate_metadata_fingerprint(directory_path: str) -> Tuple[str, int]:
    """
    极速元数据指纹计算。
    不读取文件内容，仅扫描系统级的 文件路径、大小(Size) 和 修改时间(Mtime)。
    耗时通常在 0.1 - 0.5 秒之间。
    """
    manifest_lines = []
    file_count = 0
    
    # 递归遍历辅助函数
    def scan_dir(path):
        nonlocal file_count
        with os.scandir(path) as it:
            for entry in it:
                # 过滤无用隐藏文件，严格排除基准文件自身
                if entry.name in ['.DS_Store', 'Thumbs.db', 'manifest_fast.json'] or entry.name.startswith('._'):
                    continue
                
                if entry.is_file(follow_symlinks=False):
                    stat = entry.stat()
                    # 提取相对路径
                    rel_path = os.path.relpath(entry.path, directory_path).replace(os.sep, '/')
                    # 核心：拼接 路径 + 大小 + 最后修改时间戳
                    # 任何对文件的修改都会导致 size 或 mtime 变化
                    line = f"{rel_path}|{stat.st_size}|{stat.st_mtime}"
                    manifest_lines.append(line)
                    file_count += 1
                elif entry.is_dir(follow_symlinks=False):
                    scan_dir(entry.path)
                    
    scan_dir(directory_path)
    
    # 按字典序强制排序以保证一致性
    manifest_lines.sort()
    
    # 将所有元数据字符串拼接，计算出一个最终的 MD5
    manifest_content = "\n".join(manifest_lines)
    dataset_md5 = hashlib.md5(manifest_content.encode('utf-8')).hexdigest()
    
    return dataset_md5, file_count

class FastDatasetTester:
    def __init__(self, dataset_path: str):
        self.dataset_path = dataset_path
        self.manifest_path = os.path.join(dataset_path, "manifest_fast.json")

    def run_initial_scan(self):
        print(f"\n🚀 [极速阶段 1] 首次扫描 (目标限制: < 5秒)")
        print("-" * 50)
        
        start_time = time.perf_counter()
        dataset_md5, file_count = calculate_metadata_fingerprint(self.dataset_path)
        elapsed_time = time.perf_counter() - start_time
        
        print(f"✅ 扫描完成! 共处理 {file_count} 个文件。")
        print(f"⏱️ 耗时: {elapsed_time:.4f} 秒 (目标达成度: {'极佳 🟢' if elapsed_time < 5 else '失败 🔴'})")
        print(f"📊 极速全局指纹: {dataset_md5}")
        
        # 保存基准
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump({"dataset_md5": dataset_md5}, f)
        print(f"💾 基准已保存。")

    def run_recheck_scan(self):
        print(f"\n🔍 [极速阶段 2] 变更复查测试 (目标限制: < 3秒)")
        print("-" * 50)
        
        if not os.path.exists(self.manifest_path):
            print("❌ 找不到基准清单！")
            return
            
        print("请手动去数据集文件夹里做些修改（改内容/删文件/加文件）。")
        input("👉 修改完成后，请按回车键立即执行秒级复查...")
        
        start_time = time.perf_counter()
        
        # 1. 重新计算指纹
        new_md5, _ = calculate_metadata_fingerprint(self.dataset_path)
        
        # 2. 读取旧指纹
        with open(self.manifest_path, 'r', encoding='utf-8') as f:
            old_md5 = json.load(f)["dataset_md5"]
            
        elapsed_time = time.perf_counter() - start_time
        
        print(f"\n✅ 复查完成! 耗时: {elapsed_time:.4f} 秒 (目标达成度: {'极佳 🟢' if elapsed_time < 3 else '失败 🔴'})")
        
        if old_md5 == new_md5:
            print("🟢 结论：数据集完好无损。")
        else:
            print("🔴 结论：警告！检测到数据集发生变更！(拒绝导入或触发重新同步)")

if __name__ == "__main__":
    # ⚠️ 替换为你真实的 20GB 数据集文件夹路径
    REAL_DATASET_PATH = r"E:\viewer\shuju\MZ20160222DS_histone49_html\MZ20160222DS_histone49_html"  
    
    tester = FastDatasetTester(REAL_DATASET_PATH)
    tester.run_initial_scan()
    tester.run_recheck_scan()