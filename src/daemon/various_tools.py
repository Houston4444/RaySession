
translator_instance = None

def setTranslator(translator):
    global translator_instance
    translator_instance = translator
    
def getTranslator():
    return translator_instance
    
class Translator():
    @staticmethod
    def get():
        return translator_instance
    
    @staticmethod
    def setInstance(translate):
        global translator_instance
        translator_instance = translate 
        
        
