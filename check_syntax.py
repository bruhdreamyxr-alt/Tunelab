import ast
src = open('ui.py', encoding='utf-8').read()
try:
    ast.parse(src)
    print('OK')
except SyntaxError as e:
    print('ERR', e.lineno, e.msg)
    print(repr(src.splitlines()[e.lineno-1]))
