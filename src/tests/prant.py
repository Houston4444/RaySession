# import io
# from contextlib import redirect_stdout

# f = io.StringIO()

# def print(*args):
#     print('titi', *args)

# def cohu(arg):
#     print('choii', arg, type(arg))
#     print(' necarotis')

# with redirect_stdout(f):
#     cohu('pok')

# out = f.getvalue()

# print(f'out :"{out}"')

# print('eirf', f.read())
# with redirect_stdout(f):
#     cohu('pokok')

# out = f.getvalue()
