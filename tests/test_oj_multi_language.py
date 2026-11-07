# -*- coding: utf-8 -*-
"""OJ 多语言判题回归门（v6.9 阶段 1：Java + JavaScript；阶段 2：C + C++）。

分两档：
1. 静态/注册档（不依赖工具链，任何机器都跑）：适配器注册表、各语言静态防呆拒绝、
   未注册语言回落。
2. 实跑档（需本机工具链）：AC/WA/RE/TLE/CE 全链评测；缺 javac/node/gcc/g++ 时自动 skip，
   避免 CI（仅 Python）假红。定位与 test_oj_runner.py 一致。
"""
import shutil

import pytest

from oj import services as oj_services
from oj.adapters import get_adapter, supported_languages
from oj.adapters._toolchain import find_compiler

_HAS_JDK = shutil.which('javac') is not None and shutil.which('java') is not None
_HAS_NODE = shutil.which('node') is not None
# C/C++ 走与 adapter 同源的三级发现（含项目内 tools/mingw64 便携工具链）
_HAS_GCC = find_compiler('gcc', 'OJ_GCC_PATH', 'OJ_GCC_PATH') is not None
_HAS_GXX = find_compiler('g++', 'OJ_GPP_PATH', 'OJ_GPP_PATH') is not None
requires_jdk = pytest.mark.skipif(not _HAS_JDK, reason='本机无 JDK，跳过 Java 实跑')
requires_node = pytest.mark.skipif(not _HAS_NODE, reason='本机无 Node，跳过 JS 实跑')
requires_gcc = pytest.mark.skipif(not _HAS_GCC, reason='本机无 gcc，跳过 C 实跑')
requires_gxx = pytest.mark.skipif(not _HAS_GXX, reason='本机无 g++，跳过 C++ 实跑')

JAVA_ECHO = (
    'import java.util.Scanner;\n'
    'public class Main {\n'
    '  public static void main(String[] args) {\n'
    '    Scanner sc = new Scanner(System.in);\n'
    '    System.out.println(sc.nextInt() + 1);\n'
    '  }\n'
    '}\n'
)
JAVA_CE = 'public class Main { void broken( {'      # 语法错误 → 编译失败
JAVA_RE = (
    'public class Main {\n'
    '  public static void main(String[] a) {\n'
    '    int[] x = new int[0];\n'
    '    System.out.println(x[5]);\n'
    '  }\n'
    '}\n'
)
JAVA_TLE = (
    'public class Main {\n'
    '  public static void main(String[] a) {\n'
    '    while (true) { }\n'
    '  }\n'
    '}\n'
)
JAVA_DANGER = ('public class Main { public static void main(String[] x)'
               '{ Runtime.getRuntime().exec("dir"); } }')

JS_ECHO = 'console.log(41 + 1)'
JS_CE = 'function {'                                # 语法错误 → node --check 失败
JS_RE = 'null.foo'
JS_TLE = 'while (true) {}'
JS_DANGER = 'require("child_process").exec("dir")'

C_ECHO = (
    '#include <stdio.h>\n'
    'int main(){int a,b;scanf("%d %d",&a,&b);printf("%d\\n",a+b);return 0;}\n'
)
C_CE = 'int main(){ return 0'                       # 缺分号/括号 → 编译失败
C_RE = (
    '#include <stdio.h>\n'
    'int main(){int a;scanf("%d",&a);printf("%d\\n",100/a);return 0;}\n'   # a=0 → SIGFPE
)
C_TLE = 'int main(){ while(1){} return 0; }'
C_DANGER = '#include <stdlib.h>\nint main(){ system("dir"); return 0; }'

CPP_ECHO = (
    '#include <iostream>\n'
    'int main(){int a,b;std::cin>>a>>b;std::cout<<a+b<<std::endl;return 0;}\n'
)
CPP_CE = 'int main(){ return 0'
CPP_RE = (
    '#include <iostream>\n'
    'int main(){int a;std::cin>>a;std::cout<<100/a<<std::endl;return 0;}\n'
)
CPP_TLE = 'int main(){ while(true){} return 0; }'
CPP_DANGER = '#include <fstream>\nint main(){ std::ofstream f("x.txt"); f<<1; return 0; }'


# ── 静态/注册档（无工具链依赖）────────────────────────────────────────
class TestRegistry:
    def test_languages_registered(self):
        langs = supported_languages()
        assert {'python', 'java', 'javascript', 'c', 'cpp'} <= langs
        assert get_adapter('JAVA') is not None          # 大小写归一
        assert get_adapter('CPP') is not None           # C++ 大小写归一
        assert get_adapter('ruby') is None              # 未注册

    def test_java_static_reject(self):
        assert get_adapter('java').check(JAVA_DANGER) is not None   # Runtime.exec 危险
        assert get_adapter('java').check(JAVA_ECHO) is None          # 干净代码（含 java.util.Scanner 导入）应放行

    def test_js_static_reject(self):
        assert get_adapter('javascript').check(JS_DANGER) is not None
        assert get_adapter('javascript').check('console.log(1)') is None

    def test_c_static_reject(self):
        assert get_adapter('c').check(C_DANGER) is not None          # system() 危险
        assert get_adapter('c').check(C_ECHO) is None                # scanf/printf 干净代码放行

    def test_cpp_static_reject(self):
        assert get_adapter('cpp').check(CPP_DANGER) is not None      # ofstream 文件写危险
        assert get_adapter('cpp').check(CPP_ECHO) is None            # cin/cout 干净代码放行

    def test_empty_rejected(self):
        assert get_adapter('java').check('   ') is not None
        assert get_adapter('javascript').check('') is not None
        assert get_adapter('c').check('') is not None
        assert get_adapter('cpp').check('') is not None


# ── Java 实跑档 ──────────────────────────────────────────────────────
@requires_jdk
class TestJavaGrade:
    def test_ac(self):
        r = oj_services.grade(JAVA_ECHO, 'java', [{'input': '41', 'expected': '42'}])
        assert r['supported'] and r['verdict'] == 'AC'

    def test_wa(self):
        r = oj_services.grade(JAVA_ECHO, 'java', [{'input': '41', 'expected': '999'}])
        assert r['verdict'] == 'WA'

    def test_ce(self):
        r = oj_services.grade(JAVA_CE, 'java', [{'input': '', 'expected': 'x'}])
        assert r['supported'] and r['verdict'] == 'CE'

    def test_re(self):
        r = oj_services.grade(JAVA_RE, 'java', [{'input': '', 'expected': '0'}])
        assert r['verdict'] == 'RE'

    def test_tle(self):
        r = oj_services.grade(JAVA_TLE, 'java', [{'input': '', 'expected': '1'}], per_case_timeout=1.0)
        assert r['verdict'] == 'TLE'

    def test_se_static(self):
        r = oj_services.grade(JAVA_DANGER, 'java', [{'input': '', 'expected': '1'}])
        assert r['supported'] and r['verdict'] == 'SE'


# ── JavaScript 实跑档 ─────────────────────────────────────────────────
@requires_node
class TestJavaScriptGrade:
    def test_ac(self):
        r = oj_services.grade(JS_ECHO, 'javascript', [{'input': '', 'expected': '42'}])
        assert r['supported'] and r['verdict'] == 'AC'

    def test_wa(self):
        r = oj_services.grade(JS_ECHO, 'javascript', [{'input': '', 'expected': '7'}])
        assert r['verdict'] == 'WA'

    def test_ce(self):
        r = oj_services.grade(JS_CE, 'javascript', [{'input': '', 'expected': 'x'}])
        assert r['supported'] and r['verdict'] == 'CE'

    def test_re(self):
        r = oj_services.grade(JS_RE, 'javascript', [{'input': '', 'expected': 'x'}])
        assert r['verdict'] == 'RE'

    def test_tle(self):
        r = oj_services.grade(JS_TLE, 'javascript', [{'input': '', 'expected': '1'}], per_case_timeout=1.0)
        assert r['verdict'] == 'TLE'

    def test_se_static(self):
        r = oj_services.grade(JS_DANGER, 'javascript', [{'input': '', 'expected': '1'}])
        assert r['supported'] and r['verdict'] == 'SE'


# ── C 实跑档（需 gcc）───────────────────────────────────────────
@requires_gcc
class TestCGrade:
    def test_ac(self):
        r = oj_services.grade(C_ECHO, 'c', [{'input': '3 5', 'expected': '8'},
                                            {'input': '100 200', 'expected': '300'}])
        assert r['supported'] and r['verdict'] == 'AC'

    def test_wa(self):
        r = oj_services.grade(C_ECHO, 'c', [{'input': '3 5', 'expected': '999'}])
        assert r['verdict'] == 'WA'

    def test_ce(self):
        r = oj_services.grade(C_CE, 'c', [{'input': '', 'expected': 'x'}])
        assert r['supported'] and r['verdict'] == 'CE'

    def test_re(self):
        r = oj_services.grade(C_RE, 'c', [{'input': '0', 'expected': 'x'}])
        assert r['verdict'] == 'RE'

    def test_tle(self):
        r = oj_services.grade(C_TLE, 'c', [{'input': '', 'expected': '1'}], per_case_timeout=1.0)
        assert r['verdict'] == 'TLE'

    def test_se_static(self):
        r = oj_services.grade(C_DANGER, 'c', [{'input': '', 'expected': '1'}])
        assert r['supported'] and r['verdict'] == 'SE'


# ── C++ 实跑档（需 g++）──────────────────────────────────────────
@requires_gxx
class TestCppGrade:
    def test_ac(self):
        r = oj_services.grade(CPP_ECHO, 'cpp', [{'input': '10 32', 'expected': '42'}])
        assert r['supported'] and r['verdict'] == 'AC'

    def test_wa(self):
        r = oj_services.grade(CPP_ECHO, 'cpp', [{'input': '10 32', 'expected': '7'}])
        assert r['verdict'] == 'WA'

    def test_ce(self):
        r = oj_services.grade(CPP_CE, 'cpp', [{'input': '', 'expected': 'x'}])
        assert r['supported'] and r['verdict'] == 'CE'

    def test_re(self):
        r = oj_services.grade(CPP_RE, 'cpp', [{'input': '0', 'expected': 'x'}])
        assert r['verdict'] == 'RE'

    def test_tle(self):
        r = oj_services.grade(CPP_TLE, 'cpp', [{'input': '', 'expected': '1'}], per_case_timeout=1.0)
        assert r['verdict'] == 'TLE'

    def test_se_static(self):
        r = oj_services.grade(CPP_DANGER, 'cpp', [{'input': '', 'expected': '1'}])
        assert r['supported'] and r['verdict'] == 'SE'
