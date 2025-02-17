

from typing import Iterator, Literal

d = {'i': 'int',
     'f': 'float',
     's': 'str',
     'b': 'bytes',
     'h': 'int',
     'd': 'float',
     'I': 'float'}
                
def parse_types(types: str, len: int) -> Iterator[str]:
    if len <= 0:
        return
    
    if len == 1:
        for c in types:
            yield c
    
    for c in types:
        for ret in parse_types(types, len - 1):
            yield c + ret
    
all_tuples = dict[str, list[str]]()

for i in range(2, 9):
    for types in parse_types('isf', i):
        key = f"tuple[{', '.join([d[c] for c in types])}]"
        if all_tuples.get(key) is None:
            all_tuples[key] = [f"Literal['{types}']"]
        else:
            all_tuples[key].append(f"Literal['{types}']")

methods = list[str]()
for tup, listype in all_tuples.items():
    methods.append(
        '    @overload\n'
        f"    def unpack(self, types: {' | '.join(listype)}) -> {tup}: ...")
print('\n'.join(methods))
print(len(methods))
# for cn in range(ns - 1, -1, -1):
#     for c in 'ifs':
#         t[cn] = c
#         print(''.join(t), cn, c)
