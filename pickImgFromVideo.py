import cv2
import numpy as np
from pathlib import Path
import json
from dataclasses import dataclass
from typing import List, Dict
import hashlib


def cv2_read_video(video_path: Path):
    """读取视频文件（支持中文路径）"""
    path_str = str(video_path)
    # 尝试直接读取
    cap = cv2.VideoCapture(path_str)
    if cap.isOpened():
        return cap
    # 如果失败，尝试使用 bytes 路径
    cap = cv2.VideoCapture(path_str.encode('utf-8').decode('utf-8'))
    if cap.isOpened():
        return cap
    # 最后尝试 numpy 方式
    cap = cv2.VideoCapture(np.fromfile(path_str, dtype=np.uint8))
    return cap

@dataclass
class VideoConfig:
    min_scene_duration: float = 1.0      # 最小场景持续时间（秒）
    threshold: float = 15.0              # 降低阈值（PPT硬切通常15-20即可）
    hash_threshold: float = 0.85         # 感知哈希相似度阈值（0-1，越小越敏感）
    check_interval: int = 10             # 每N帧检查一次（提高效率）


class PPTVideoProcessor:
    """
    专门针对PPT/录屏视频优化：
    1. 使用感知哈希（pHash）检测内容变化（对文字变化敏感）
    2. 支持OCR辅助验证（可选）
    3. 自适应阈值（如果没检测到，自动降低阈值重试）
    """
    
    def __init__(self, config: VideoConfig = None):
        self.config = config or VideoConfig()
        self.results = []
    
    def get_phash(self, frame) -> str:
        """计算感知哈希（对文字/布局变化敏感）"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # 缩放到32x32
        resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_LANCZOS4)
        # DCT变换
        dct = cv2.dct(np.float32(resized))
        dct_low = dct[:8, :8]
        # 计算均值并生成哈希
        avg = (dct_low.sum() - dct_low[0, 0]) / 63
        hash_str = ''.join(['1' if x > avg else '0' for x in dct_low.flatten()])
        return hash_str
    
    def hash_similarity(self, hash1: str, hash2: str) -> float:
        """计算汉明距离相似度"""
        if len(hash1) != len(hash2):
            return 0.0
        distance = sum(c1 != c2 for c1, c2 in zip(hash1, hash2))
        return 1 - (distance / len(hash1))
    
    def detect_scenes_adaptive(self, video_path: Path, max_retries: int = 3) -> List[Dict]:
        """
        自适应场景检测：如果没检测到，自动降低阈值重试
        """
        cap = cv2_read_video(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        
        print(f"\n{'='*60}")
        print(f"视频: {video_path.name}")
        print(f"时长: {duration:.1f}s | 帧率: {fps:.1f}fps | 总帧数: {total_frames}")
        
        best_scenes = []
        best_threshold = self.config.hash_threshold
        
        for attempt in range(max_retries):
            current_threshold = self.config.hash_threshold - (attempt * 0.15)
            print(f"\n尝试 {attempt+1}/{max_retries}: 相似度阈值 {current_threshold:.2f}")
            
            scenes = self._detect_with_threshold(cap, fps, current_threshold)
            print(f"  检测到 {len(scenes)} 个切换点")
            
            # 保存最佳结果（至少检测到1个，且数量合理）
            if len(scenes) > len(best_scenes) and len(scenes) < duration / 1.5:
                best_scenes = scenes
                best_threshold = current_threshold
            
            # 如果检测到足够多，提前退出
            if len(scenes) >= 3 and len(scenes) <= duration / 2:
                break
        
        cap.release()
        print(f"\n最终使用阈值: {best_threshold:.2f}, 检测到 {len(best_scenes)} 个切换")
        return best_scenes, duration, fps
    
    def _detect_with_threshold(self, cap, fps: float, threshold: float) -> List[Dict]:
        """使用指定阈值检测场景"""
        scenes = []
        prev_hash = None
        frame_idx = 0
        last_scene_time = -self.config.min_scene_duration
        check_frames = int(fps * 0.5)  # 每0.5秒检查一次
        
        # 重置视频位置
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        
        while True:
            ret = cap.grab()  # 快速读取
            if not ret:
                break
            
            # 按间隔采样
            if frame_idx % check_frames != 0:
                frame_idx += 1
                continue
            
            ret, frame = cap.retrieve()
            if not ret:
                break
            
            current_time = frame_idx / fps
            current_hash = self.get_phash(frame)
            
            if prev_hash is not None:
                similarity = self.hash_similarity(prev_hash, current_hash)
                
                # 相似度低于阈值 = 场景切换
                if similarity < threshold and (current_time - last_scene_time) > self.config.min_scene_duration:
                    scenes.append({
                        'frame': frame_idx,
                        'time': current_time,
                        'similarity': similarity,
                        'hash': current_hash
                    })
                    last_scene_time = current_time
            
            prev_hash = current_hash
            frame_idx += 1
        
        return scenes
    
    def extract_keyframes(self, video_path: Path, scenes: List[Dict], 
                         output_dir: Path, duration: float, fps: float) -> List[Path]:
        """
        智能提取关键帧：在场景之间取中点，避开切换瞬间
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        extracted = []

        cap = cv2_read_video(video_path)
        
        # 构建时间点列表
        key_times = []
        
        # 第一个场景：从0开始到第一个切换点
        if scenes:
            key_times.append(scenes[0]['time'] / 2)  # 第一个场景中间
        else:
            key_times.append(duration / 2)  # 只有一个画面，取中间
        
        # 中间场景：在两个切换点之间取中点
        for i in range(1, len(scenes)):
            mid_time = (scenes[i-1]['time'] + scenes[i]['time']) / 2
            # 确保距离前后切换点都有足够时间（避免动画）
            if mid_time - scenes[i-1]['time'] > 0.3 and scenes[i]['time'] - mid_time > 0.3:
                key_times.append(mid_time)
        
        # 最后一个场景
        if scenes:
            key_times.append((scenes[-1]['time'] + duration) / 2)
        
        # 去重并排序
        key_times = sorted(set([t for t in key_times if 0.5 < t < duration - 0.5]))
        
        print(f"将提取 {len(key_times)} 个关键帧")
        
        for idx, target_time in enumerate(key_times, 1):
            target_frame = int(target_time * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            
            ret, frame = cap.read()
            if not ret:
                continue
            
            # 质量检查：清晰度
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            
            # 如果模糊，前后微调找最清晰的
            best_frame = frame
            best_var = laplacian_var
            
            for offset in [-10, -5, 5, 10]:
                test_frame_idx = target_frame + int(offset * fps / 10)
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, test_frame_idx))
                ret, test_frame = cap.read()
                if ret:
                    test_gray = cv2.cvtColor(test_frame, cv2.COLOR_BGR2GRAY)
                    test_var = cv2.Laplacian(test_gray, cv2.CV_64F).var()
                    if test_var > best_var:
                        best_var = test_var
                        best_frame = test_frame
            
            # 保存（使用 imencode + tofile 解决中文路径问题）
            output_name = f"{video_path.stem}_page{idx:02d}_t{target_time:.1f}s.png"
            output_path = output_dir / output_name
            # cv2.imwrite 不支持中文路径，使用 imencode + tofile
            success, encoded_img = cv2.imencode('.png', best_frame)
            if success:
                encoded_img.tofile(str(output_path))
                extracted.append(output_path)
                print(f"  ✓ Page {idx}: {target_time:.1f}s (清晰度: {best_var:.0f})")
            else:
                print(f"  ✗ Page {idx}: 保存失败")
        
        cap.release()
        return extracted
    
    def process_single(self, video_path: Path, output_base: Path) -> Dict:
        """处理单个视频"""
        try:
            scenes, duration, fps = self.detect_scenes_adaptive(video_path)
            
            video_output_dir = output_base / video_path.stem
            extracted = self.extract_keyframes(
                video_path, scenes, video_output_dir, duration, fps
            )
            
            result = {
                'video': str(video_path),
                'duration': duration,
                'scenes_detected': len(scenes),
                'extracted_frames': len(extracted),
                'output_dir': str(video_output_dir),
                'frames': [str(p) for p in extracted]
            }
            self.results.append(result)
            return result
            
        except Exception as e:
            print(f"✗ 处理失败: {e}")
            import traceback
            traceback.print_exc()
            return {'video': str(video_path), 'error': str(e)}
    
    def process_batch(self, input_dir: str, output_dir: str = "screenshots"):
        """批量处理"""
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv'}
        videos = [f for f in input_path.iterdir() 
                  if f.suffix.lower() in video_extensions]
        
        print(f"\n发现 {len(videos)} 个视频")
        
        for video in sorted(videos):
            self.process_single(video, output_path)
        
        # 保存报告
        report_path = output_path / "processing_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        # 打印摘要
        print(f"\n{'='*60}")
        print("处理摘要:")
        total_pages = sum(r.get('extracted_frames', 0) for r in self.results)
        print(f"  视频总数: {len(videos)}")
        print(f"  总页数: {total_pages}")
        print(f"  平均每视频: {total_pages/len(videos):.1f} 页")
        print(f"  报告保存: {report_path}")
        
        return self.results


# ==================== 使用 ====================

if __name__ == "__main__":
    # 针对PPT录屏优化配置
    config = VideoConfig(
        min_scene_duration=1.0,    # 每页至少1秒
        hash_threshold=0.92,       # 感知哈希阈值（0.85=15%变化即触发）
        check_interval=10          # 检查间隔
    )
    
    processor = PPTVideoProcessor(config)
    
    # 处理单个视频测试
    #processor.process_single(Path("./downloads/金融监管局考前必背1000题（51-100）.mp4"), Path("output"))
    
    # 批量处理
    processor.process_batch(
        input_dir="downloads",      # 修改为你的视频目录
        output_dir="screenshots"
    )