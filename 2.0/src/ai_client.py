"""
AI客户端封装模块
负责与OpenAI兼容的API进行交互
"""
from openai import OpenAI
from typing import List, Dict, Any, Optional
import json


class AIClient:
    """AI客户端类"""
    
    def __init__(self, base_url: str, api_key: str, model: str):
        """初始化AI客户端"""
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        self.model = model
    
    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        """发送聊天请求并返回响应"""
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
            )
            return completion.choices[0].message.content
        except Exception as e:
            raise Exception(f"AI请求失败: {str(e)}")
    
    def ask_with_context(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
        """使用系统提示和用户提示进行对话"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        return self.chat(messages, temperature)
    
    def parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应"""
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            # 如果失败，尝试提取代码块中的JSON
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                json_str = response[start:end].strip()
                return json.loads(json_str)
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                json_str = response[start:end].strip()
                return json.loads(json_str)
            else:
                raise ValueError(f"无法解析JSON响应: {response}")

