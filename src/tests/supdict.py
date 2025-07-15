import time

def parse_dict(d: dict):
    bef = time.time()
    for v, w in d.items():
        if w:
            ...
    aft = time.time()
    print(aft - bef)

def parse_list(l: list):
    bef = time.time()
    for el in l:
        if el:
            ...
    aft = time.time()
    print(aft - bef)
    
li = [str(i) for i in range(1000)]
di = {}
for i in range(1000):
    di[f'{i}'] = str(i)
    
print('parese dict')
parse_dict(di)
print('parse list')
parse_list(li)


