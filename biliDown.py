#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站视频下载脚本
支持单视频及合集视频下载，支持时间范围裁剪
"""

import os
import re
import json
import requests
import subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from typing import Optional, Tuple, List, Dict


class BiliDownloader:
    def __init__(self, output_dir: str = "./downloads"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com",
        })

    def extract_video_id(self, url: str) -> Tuple[str, Optional[int]]:
        """
        从URL中提取视频ID
        返回: (视频ID类型和值, 分P号)
        """
        # BV号
        bv_match = re.search(r'BV[\w]+', url)
        if bv_match:
            bv_id = bv_match.group()
            # 提取分P号
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            p_num = int(query.get('p', [1])[0])
            return (f"bvid:{bv_id}", p_num)

        # AV号
        av_match = re.search(r'av(\d+)', url, re.IGNORECASE)
        if av_match:
            aid = av_match.group(1)
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            p_num = int(query.get('p', [1])[0])
            return (f"aid:{aid}", p_num)

        raise ValueError(f"无法从URL中提取视频ID: {url}")

    def get_video_info(self, video_id: str) -> dict:
        """获取视频基本信息"""
        id_type, id_value = video_id.split(':')

        if id_type == 'bvid':
            api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={id_value}"
        else:
            api_url = f"https://api.bilibili.com/x/web-interface/view?aid={id_value}"

        response = self.session.get(api_url)
        response.raise_for_status()
        data = response.json()

        if data['code'] != 0:
            raise Exception(f"获取视频信息失败: {data['message']}")

        return data['data']

    def get_playurl(self, bvid: str, cid: int) -> dict:
        """获取视频播放地址"""
        api_url = "https://api.bilibili.com/x/player/wbi/playurl"
        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": 80,  # 80=高清1080P, 64=高清720P, 32=清晰480P
            "fnval": 16,  # 16=dash格式
            "fnver": 0,
            "fourk": 1,
        }

        response = self.session.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()

        if data['code'] != 0:
            raise Exception(f"获取播放地址失败: {data['message']}")

        return data['data']

    def sanitize_filename(self, filename: str) -> str:
        """清理文件名中的非法字符"""
        illegal_chars = r'[<>:"/\\|?*]'
        return re.sub(illegal_chars, '_', filename)

    def download_file(self, url: str, filepath: Path, desc: str = "下载中") -> bool:
        """下载文件"""
        try:
            response = self.session.get(url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            print(f"\r{desc}: {progress:.1f}%", end='', flush=True)

            print()
            return True
        except Exception as e:
            print(f"\n下载失败: {e}")
            return False

    def merge_video_audio(self, video_path: Path, audio_path: Path, output_path: Path,
                          start_time: Optional[str] = None, end_time: Optional[str] = None) -> bool:
        """合并视频和音频，支持时间裁剪"""
        try:
            # 检查ffmpeg是否可用
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("错误: 未找到ffmpeg，请先安装ffmpeg并添加到PATH")
            return False

        cmd = ['ffmpeg', '-y']

        # 对视频输入添加时间参数
        if start_time:
            cmd.extend(['-ss', start_time])
        cmd.extend(['-i', str(video_path)])

        # 对音频输入添加时间参数（需要单独设置）
        if start_time:
            cmd.extend(['-ss', start_time])
        cmd.extend(['-i', str(audio_path)])

        # 结束时间
        if end_time:
            cmd.extend(['-to', end_time])

        cmd.extend([
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-strict', 'experimental',
            str(output_path)
        ])

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"合并失败: {e.stderr.decode() if e.stderr else str(e)}")
            return False

    def download_single_video(self, url: str, start_time: Optional[str] = None,
                               end_time: Optional[str] = None) -> bool:
        """下载单个视频"""
        print(f"\n开始处理: {url}")

        # 提取视频ID
        video_id, p_num = self.extract_video_id(url)
        id_type, id_value = video_id.split(':')

        # 获取视频信息
        print("获取视频信息...")
        video_info = self.get_video_info(video_id)

        title = self.sanitize_filename(video_info['title'])
        bvid = video_info['bvid']

        # 获取对应分P的cid
        pages = video_info.get('pages', [])
        if pages:
            cid = pages[p_num - 1]['cid'] if p_num <= len(pages) else pages[0]['cid']
            page_title = pages[p_num - 1].get('part', '') if p_num <= len(pages) else ''
            if page_title:
                title = self.sanitize_filename(f"{title}_P{p_num}_{page_title}")
            elif len(pages) > 1:
                title = self.sanitize_filename(f"{title}_P{p_num}")
        else:
            cid = video_info['cid']

        print(f"视频标题: {title}")

        # 获取播放地址
        print("获取播放地址...")
        playurl_data = self.get_playurl(bvid, cid)

        dash = playurl_data.get('dash', {})
        if not dash:
            # 非DASH格式，尝试获取flv/mp4链接
            durl = playurl_data.get('durl', [])
            if durl:
                video_url = durl[0]['url']
                output_path = self.output_dir / f"{title}.mp4"
                print(f"开始下载: {title}.mp4")
                if self.download_file(video_url, output_path, "下载视频"):
                    print(f"下载完成: {output_path}")
                    return True
            print("无法获取视频下载地址")
            return False

        # DASH格式，分别下载视频和音频
        video_streams = dash.get('video', [])
        audio_streams = dash.get('audio', [])

        if not video_streams:
            print("未找到视频流")
            return False

        # 选择最高清晰度视频
        video_stream = video_streams[0]
        video_url = video_stream['baseUrl'] or video_stream['base_url']

        audio_url = None
        if audio_streams:
            audio_stream = audio_streams[0]
            audio_url = audio_stream['baseUrl'] or audio_stream['base_url']

        # 下载视频
        temp_video = self.output_dir / f"{title}_video.m4s"
        print(f"下载视频流...")
        if not self.download_file(video_url, temp_video, "下载视频"):
            return False

        # 下载音频
        temp_audio = self.output_dir / f"{title}_audio.m4s"
        if audio_url:
            print("下载音频流...")
            if not self.download_file(audio_url, temp_audio, "下载音频"):
                temp_video.unlink(missing_ok=True)
                return False

        # 合并
        output_path = self.output_dir / f"{title}.mp4"
        print("合并视频和音频...")

        if self.merge_video_audio(temp_video, temp_audio, output_path, start_time, end_time):
            # 清理临时文件
            temp_video.unlink(missing_ok=True)
            temp_audio.unlink(missing_ok=True)
            print(f"下载完成: {output_path}")
            return True
        else:
            # 保留临时文件
            print(f"合并失败，临时文件保留在: {temp_video}, {temp_audio}")
            return False

    def download_collection(self, url: str, start_time: Optional[str] = None,
                            end_time: Optional[str] = None,
                            start_p: Optional[int] = None,
                            end_p: Optional[int] = None) -> List[bool]:
        """下载合集视频"""
        print(f"\n开始处理合集: {url}")

        # 提取视频ID
        video_id, _ = self.extract_video_id(url)

        # 获取视频信息
        print("获取视频信息...")
        video_info = self.get_video_info(video_id)

        pages = video_info.get('pages', [])
        if not pages:
            print("这不是合集视频，尝试作为单视频下载...")
            return [self.download_single_video(url, start_time, end_time)]

        total_pages = len(pages)
        print(f"合集共 {total_pages} 个视频")

        # 确定下载范围
        start_idx = (start_p - 1) if start_p else 0
        end_idx = end_p if end_p else total_pages

        start_idx = max(0, start_idx)
        end_idx = min(total_pages, end_idx)

        print(f"将下载第 {start_idx + 1} 到第 {end_idx} 个视频")

        results = []
        base_title = self.sanitize_filename(video_info['title'])
        bvid = video_info['bvid']

        for i in range(start_idx, end_idx):
            page = pages[i]
            cid = page['cid']
            page_title = page.get('part', f"P{i+1}")
            title = self.sanitize_filename(f"{base_title}_P{i+1}_{page_title}")

            print(f"\n[{i+1}/{end_idx}] 下载: {title}")

            # 获取播放地址
            try:
                playurl_data = self.get_playurl(bvid, cid)
            except Exception as e:
                print(f"获取播放地址失败: {e}")
                results.append(False)
                continue

            dash = playurl_data.get('dash', {})
            if not dash:
                durl = playurl_data.get('durl', [])
                if durl:
                    video_url = durl[0]['url']
                    output_path = self.output_dir / f"{title}.mp4"
                    if self.download_file(video_url, output_path, "下载视频"):
                        results.append(True)
                        continue
                results.append(False)
                continue

            video_streams = dash.get('video', [])
            audio_streams = dash.get('audio', [])

            if not video_streams:
                results.append(False)
                continue

            video_stream = video_streams[0]
            video_url = video_stream['baseUrl'] or video_stream['base_url']

            audio_url = None
            if audio_streams:
                audio_stream = audio_streams[0]
                audio_url = audio_stream['baseUrl'] or audio_stream['base_url']

            # 下载
            temp_video = self.output_dir / f"{title}_video.m4s"
            temp_audio = self.output_dir / f"{title}_audio.m4s"

            print("下载视频流...")
            if not self.download_file(video_url, temp_video, "下载视频"):
                results.append(False)
                continue

            if audio_url:
                print("下载音频流...")
                if not self.download_file(audio_url, temp_audio, "下载音频"):
                    temp_video.unlink(missing_ok=True)
                    results.append(False)
                    continue

            # 合并
            output_path = self.output_dir / f"{title}.mp4"
            print("合并视频和音频...")

            if self.merge_video_audio(temp_video, temp_audio, output_path, start_time, end_time):
                temp_video.unlink(missing_ok=True)
                temp_audio.unlink(missing_ok=True)
                print(f"完成: {output_path}")
                results.append(True)
            else:
                print("合并失败")
                results.append(False)

        success_count = sum(results)
        print(f"\n下载完成: 成功 {success_count}/{len(results)}")
        return results


def parse_time(time_str: str) -> str:
    """解析时间字符串，支持 HH:MM:SS 或 MM:SS 或秒数"""
    if not time_str:
        return None

    # 纯数字，当作秒数
    if time_str.isdigit():
        seconds = int(time_str)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    # 已经是时间格式
    if re.match(r'^\d+:\d+(:\d+)?$', time_str):
        return time_str

    raise ValueError(f"无效的时间格式: {time_str}，请使用 HH:MM:SS 或 MM:SS 或秒数")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='B站视频下载脚本')
    parser.add_argument('url', help='B站视频URL')
    parser.add_argument('-o', '--output', default='./downloads', help='输出目录 (默认: ./downloads)')
    parser.add_argument('-s', '--start', help='起始时间 (格式: HH:MM:SS 或 MM:SS 或秒数)，不指定结束时间则下载到视频末尾')
    parser.add_argument('-e', '--end', help='结束时间 (格式: HH:MM:SS 或 MM:SS 或秒数)')
    parser.add_argument('-p', '--start-p', type=int, help='合集起始P号')
    parser.add_argument('-P', '--end-p', type=int, help='合集结束P号')
    parser.add_argument('-c', '--collection', action='store_true', help='下载整个合集')

    args = parser.parse_args()

    # 解析时间
    start_time = parse_time(args.start) if args.start else None
    end_time = parse_time(args.end) if args.end else None

    if start_time and end_time:
        print(f"时间范围: {start_time} - {end_time}")
    elif start_time:
        print(f"起始时间: {start_time} (下载至视频末尾)")
    elif end_time:
        print(f"结束时间: {end_time}")

    downloader = BiliDownloader(args.output)

    if args.collection or args.start_p or args.end_p:
        downloader.download_collection(
            args.url,
            start_time=start_time,
            end_time=end_time,
            start_p=args.start_p,
            end_p=args.end_p
        )
    else:
        downloader.download_single_video(args.url, start_time, end_time)


if __name__ == '__main__':
    main()