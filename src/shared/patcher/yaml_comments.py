GRAPH = """DO NOT EDIT !
Is used to know if some disconnections are needed at startup.
A connection is disconnected when its two ports are present in this graph."""

NSM_BROTHERS = """DO NOT EDIT !
Is used to know if the patcher should remove some connections from memory.
Connections are removed if one of its ports belongs to a removed client.
It is also used to rename ports when a NSM client name changes."""