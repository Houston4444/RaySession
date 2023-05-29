import xml.etree.ElementTree as ET


class XmlElement:
    def __init__(self, element: ET.Element):
        self.el = element
    
    def iter(self):
        for child in self.el:
            yield XmlElement(child)
    
    def new_child(self, tag: str) -> 'XmlElement':
        return XmlElement(ET.SubElement(self.el, tag))
    
    def str(self, attribute: str, default='') -> str:
        ret_value = self.el.attrib.get(attribute)
        if ret_value is None:
            return default
        return ret_value
    
    def bool(self, attribute: str, default=False) -> bool:
        ret_value = self.el.attrib.get(attribute)
        if ret_value is None:
            return default
        
        if ret_value.lower() in ('false', 'no', '0'):
            return False
        
        return True
    
    def int(self, attribute: str, default=0) -> int:
        ret_value = self.el.attrib.get(attribute)
        if ret_value is None:
            return default
        
        if ret_value.isdigit():
            return int(ret_value)
        
        if ret_value.lower() in ('true', 'yes'):
            return 1
        
        return 0
    
    def float(self, attribute: str, default=0.0) -> float:
        ret_value = self.el.attrib.get(attribute)
        if ret_value is None:
            return default
        
        try:
            float_val = float(ret_value)
        except:
            float_val = None
            
        if float_val is not None:
            return float_val

        if ret_value.lower() in ('true', 'yes'):
            return 1.0
        
        return 0.0
    
    def set_str(self, attribute:str, value: str):
        self.el.attrib[attribute] = str(value)
        
    def set_bool(self, attribute: str, yesno: bool):
        self.el.attrib[attribute] = 'true' if yesno else 'false'
    
    def set_int(self, attribute: str, value: int):
        self.el.attrib[attribute] = str(int(value))
        
    def set_float(self, attribute: str, value: float):
        self.el.attrib[attribute] = str(float(value))
        
    def remove_attr(self, attribute: str):
        if attribute in self.el:
            self.el.pop(attribute)