import requests
import json
import re
import time
import logging
from config import Config

# 仅 AI 请求禁用系统代理（开发机代理软件会拦截方舟请求导致超时）。
# 不修改全局 os.environ，避免影响进程内其他 HTTP 库/出站请求。
_NO_PROXY = {"http": None, "https": None}

# 日志配置，控制台打印完整AI返回内容方便排错
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class AITimeoutError(Exception):
    """AI 在给定读超时内没答完。

    负载问题（体量大 / 模型侧慢），不是配置问题：同一个请求再发一次，
    只会让用户多等一个整超时并双倍消耗额度，所以这条不再重试。
    seconds：本次生效的读超时，供上层拼准确文案。
    """

    def __init__(self, message, seconds=None):
        super().__init__(message)
        self.seconds = seconds


class AINetworkError(Exception):
    """连不上方舟 / 接口报错（含密钥失效、限流等 4xx、5xx），与「答得慢」区分开。"""


class AIClient:
    def __init__(self):
        self.api_key = Config.DOUBAN_API_KEY
        self.api_url = Config.DOUBAN_API_URL
        self.model_ep_id = Config.DOUBAN_ENDPOINT_ID
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        self.timeout = int(getattr(Config, 'AI_TIMEOUT', 60))  # 默认 60 秒，长文档/出题由调用方按 AI_DOC_TIMEOUT、AI_EXAM_TIMEOUT 放宽
        self.max_retries = 2  # 只对连接类错误重试；读超时不重试（见 AITimeoutError）

    DEFAULT_SYSTEM = "你是专业出题阅卷老师，只输出用户要求的标准JSON，不要多余文字、标题、注释、换行说明"

    def _clean_json_text(self, raw_text: str) -> str:
        """清洗AI返回文本，剔除markdown、多余换行、外层包装，只保留最外层JSON（对象或数组）"""
        # 移除```json 代码块标记
        raw_text = re.sub(r'```(json)?', '', raw_text)
        raw_text = raw_text.strip()
        # 匹配最外层 {} 或 []：左到右扫描，先遇 [ 取数组、先遇 { 取对象，兼容AI额外套文字的情况
        match_res = re.search(r'\{.*\}|\[.*\]', raw_text, re.S)
        if match_res:
            return match_res.group()
        return raw_text

    def _post_ark(self, payload: dict, timeout: int = None) -> str:
        """发送火山方舟请求，返回模型原始回复文本。

        timeout：本次调用的读超时，不给则用实例默认值。出题与长文档体量差一个数量级，
        共用一个全局超时会让长文档恒降级（真机实锤），故按调用粒度可覆盖。

        重试策略按错误性质分流：连不上（连接超时/连接失败）值得再试一次；
        读超时是“模型还在写”，重发必然再等一个整超时，直接失败更快也更省额度。
        """
        t = int(timeout or self.timeout)
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            started = time.time()
            try:
                logger.info(f"API请求（第{attempt}次，读超时 {t}s，max_tokens={payload.get('max_tokens')}）...")
                resp = requests.post(
                    url=self.api_url,
                    headers=self.headers,
                    json=payload,
                    timeout=t,
                    proxies=_NO_PROXY
                )
                cost = time.time() - started
                logger.info(f"API状态码: {resp.status_code}，用时 {cost:.1f}s")
                resp.raise_for_status()  # 4xx/5xx直接抛异常
                raw_content = resp.json()["choices"][0]["message"]["content"]
                logger.info(f"AI原始返回文本:\n{raw_content}")
                return raw_content
            except requests.exceptions.ConnectTimeout as e:
                # ConnectTimeout 同时继承 Timeout 和 ConnectionError，必须排在 Timeout 前
                last_err = e
                logger.warning(f"第{attempt}次连接超时: {str(e)}")
            except requests.exceptions.ConnectionError as e:
                last_err = e
                logger.warning(f"第{attempt}次连接失败: {str(e)}")
            except requests.exceptions.Timeout as e:
                cost = time.time() - started
                logger.warning(f"读超时：{t}s 内未返回（实际等待 {cost:.1f}s，本次不重试）")
                raise AITimeoutError(f"AI 响应超时：{t}s 内未返回", seconds=t)
            except requests.exceptions.RequestException as e:
                # HTTPError（密钥失效、限流、方舟侧 5xx）等归为网络/配置异常
                err_msg = f"网络请求失败: {str(e)}"
                logger.error(err_msg)
                raise AINetworkError(err_msg)
            except Exception as e:
                # 响应体结构不对等：归接口异常，不混进“网络”文案
                err_msg = f"AI接口处理异常: {str(e)}"
                logger.error(err_msg)
                raise AINetworkError(err_msg)
            if attempt < self.max_retries:
                logger.info("连接类失败，自动重试中...")
        # 连接重试耗尽
        raise AINetworkError(f"网络连接失败（已重试{self.max_retries}次）: {str(last_err)}")

    def _send_ark_request(self, prompt: str, temp: float = 0.7, max_tok: int = 2000,
                          system: str = None, clean_json: bool = True, timeout: int = None) -> str:
        """通用单轮请求封装：system 可自定义，clean_json 控制是否提取JSON，timeout 按负载放宽"""
        payload = {
            "model": self.model_ep_id,
            "messages": [
                {"role": "system", "content": (system or self.DEFAULT_SYSTEM).strip()},
                {"role": "user", "content": prompt.strip()}
            ],
            "temperature": temp,
            "max_tokens": max_tok
        }
        raw_content = self._post_ark(payload, timeout=timeout)
        if not clean_json:
            return raw_content.strip()
        clean_content = self._clean_json_text(raw_content)
        logger.info(f"清洗后JSON字符串:\n{clean_content}")
        return clean_content

    def generate_json(self, system: str, prompt: str, temp: float = 0.5, max_tok: int = 4000,
                      timeout: int = None) -> str:
        """通用JSON生成：自定义system角色，返回清洗后的标准JSON字符串（对象或数组）。

        timeout：本次调用的读超时。长产出（如心得初稿 2000 token）沿用默认 60s 会每次
        掐断，与长文档同理必须按负载放宽，不给则沿用实例默认值。
        """
        return self._send_ark_request(prompt, temp=temp, max_tok=max_tok, system=system,
                                      clean_json=True, timeout=timeout)

    def chat(self, messages: list, temp: float = 0.6, max_tok: int = 1500,
             timeout: int = None) -> str:
        """多轮对话：messages=[{role, content}]（含system），返回纯文本回复（不做JSON清洗）"""
        payload = {
            "model": self.model_ep_id,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tok
        }
        return self._post_ark(payload, timeout=timeout).strip()

    def chat_stream(self, messages: list, temp: float = 0.6, max_tok: int = 1500):
        """流式多轮对话：逐块 yield 增量文本（方舟 OpenAI 兼容 SSE）；失败抛异常由调用方降级。"""
        payload = {
            "model": self.model_ep_id,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tok,
            "stream": True
        }
        with requests.post(url=self.api_url, headers=self.headers, json=payload,
                           timeout=self.timeout, proxies=_NO_PROXY, stream=True) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    yield delta

    def generate_question(self, major: str, question_type: str, difficulty: str, count: int = 5, description: str = None, source: str = 'ai', timeout: int = None):
        """AI批量生成考试题目，返回可直接loads的纯JSON数组字符串

        timeout：本次出题的读超时。推理模型下 5 道题实测近 75s，
        不给就会沿用 60s 默认值每次掐断，由调用方按道数算好传进来。
        """
        # 题型/中文名单一事实源：QuestionTypeEnum/DifficultyEnum（v4.7 收敛，不再自带映射）
        from database.models import QuestionTypeEnum, DifficultyEnum
        type_cn = QuestionTypeEnum.label(question_type)

        difficulty_cn = DifficultyEnum.label(difficulty)

        # 针对题型生成不同的字段提示
        if question_type in ('single_choice', 'multiple_choice'):
            field_hint = '选择题：content完整题干、options字符串数组(4个选项，选项格式如"A.选项内容")、answer标准答案(如"A"或"AB")、knowledge知识点标签(多个用逗号分隔)、analysis详细解析(包含解题思路、考点分析)'
        elif question_type == 'fill_blank':
            field_hint = '填空题：content题干（空格用____表示）、options为空数组[]、answer标准答案、knowledge知识点标签(多个用逗号分隔)、analysis详细解析(包含答案来源、相关知识点)'
        elif question_type == 'true_false':
            field_hint = '判断题：content题干、options为空数组[]、answer填"正确"或"错误"、knowledge知识点标签(多个用逗号分隔)、analysis详细解析(说明判断依据和相关概念)'
        elif question_type == 'programming':
            field_hint = '编程题：content题目要求及输入输出描述、options为空数组[]、answer参考代码、knowledge知识点标签(多个用逗号分隔)、analysis详细解析(包含解题思路、算法原理、代码解释)'
        elif question_type == 'application':
            field_hint = '应用题：content应用场景描述和问题、options为空数组[]、answer完整解答过程、knowledge知识点标签(多个用逗号分隔)、analysis详细解析(包含知识点应用、解题步骤分析)'
        elif question_type == 'calculation':
            field_hint = '计算题：content计算要求、options为空数组[]、answer完整计算步骤和结果、knowledge知识点标签(多个用逗号分隔)、analysis详细解析(包含公式原理、计算过程说明)'
        else:
            field_hint = '问答题：content题干、options为空数组[]、answer参考答案、knowledge知识点标签(多个用逗号分隔)、analysis详细解析(包含核心要点、扩展说明)'

        # 出题描述
        desc_hint = f"\\n出题描述：{description}" if description else ""

        # 根据来源类型调整提示词
        if source == 'past':
            source_hint = "请参考历年真题风格生成题目，题目结构、难度分布、考察重点要符合真实考试真题的特点"
        else:
            source_hint = "请根据专业知识体系生成高质量的原创题目"

        prompt = f"""
你是一位专业的{major}专业教师，请生成{count}道{difficulty_cn}难度的{type_cn}。

要求：
1. 题目内容必须与{major}专业紧密相关，覆盖核心知识点
2. 难度适中，符合{difficulty_cn}级别要求
3. 答案准确无误
4. 知识点标签要准确匹配
5. 解析要详细、易懂，帮助学生理解
6. {source_hint}
{desc_hint}

严格仅输出JSON数组，禁止任何外层对象、文字说明、markdown、换行注释。
字段规范：{field_hint}
输出模板：
[
    {{
        "content": "题干内容",
        "options": [],
        "answer": "正确答案",
        "knowledge": "知识点1,知识点2",
        "analysis": "详细解析内容"
    }}
]
        """
        return self._send_ark_request(prompt, temp=0.7, max_tok=4000, timeout=timeout)

    def grade_answer(self, question_content: str, correct_answer: str, student_answer: str):
        """AI批改作答，返回固定JSON字符串"""
        prompt = f"""
题目：{question_content}
标准答案：{correct_answer}
学生作答：{student_answer}
评分要求：
- 客观题（选择/填空/判断）：完全一致才给满分
- 主观题（问答/编程/应用/计算）：根据思路正确性、完整性、逻辑性给分
仅输出JSON，字段：is_correct(布尔, 主观题意思相近即可为true), score(0-100整数), analysis(简短评语)
示例：{{"is_correct":true,"score":80,"analysis":"思路正确，但缺少边界处理"}}
        """
        return self._send_ark_request(prompt, temp=0.3, max_tok=800)

    def generate_analysis(self, question_content: str, correct_answer: str, student_answer: str,
                          doubt: str = None):
        """生成详细答题解析。

        doubt：学生自己的疑问。v7.20 才真正接进来——以前路由收了疑问却根本不传给本函数，
        学生写「卡在第二步移项」与什么都不写得回一模一样的泛用解析，看着像正常工作。
        没有标准答案（纯题面提问）时不能输出「标准答案：None」那种脏 prompt，故分开拼。
        """
        lines = [f"题目：{question_content}"]
        if (correct_answer or '').strip():
            lines.append(f"标准答案：{correct_answer}")
        if (student_answer or '').strip():
            lines.append(f"学生作答：{student_answer}")
        if (doubt or '').strip():
            lines.append(f"学生的疑问：{doubt}")
            lines.append('请先直接回答学生的疑问，再补上完整解题思路与考点，不要只把题重述一遍。')
        lines.append('输出详细知识点解析，无需JSON，纯中文文本即可')
        prompt = '\n' + '\n'.join(lines) + '\n'
        return self._send_ark_request(prompt, temp=0.5, max_tok=1200)