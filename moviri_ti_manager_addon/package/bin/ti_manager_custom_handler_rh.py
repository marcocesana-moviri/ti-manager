from splunktaucclib.rest_handler.admin_external import AdminExternalHandler

import os

class TiManagerCustomHandler(AdminExternalHandler):
    def __init__(self, *args, **kwargs):
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleList(self, confInfo):
        AdminExternalHandler.handleList(self, confInfo)

    def handleEdit(self, confInfo):
        AdminExternalHandler.handleEdit(self, confInfo)

    def handleCreate(self, confInfo):
        AdminExternalHandler.handleCreate(self, confInfo)

    def handleRemove(self, confInfo):
        normalized_input_name = self.callerArgs.id
        csv_name = f"{normalized_input_name}.csv"
        # 2. Calcola i percorsi in cui potrebbe trovarsi il file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # A seconda di dove è posizionato questo script (es. bin/), 
        # risaliamo alla root dell'app per puntare alla cartella lookups
        lookups_base_dir = os.path.abspath(os.path.join(script_dir, "..", "lookups"))
        
        paths_to_check = [
            os.path.join(lookups_base_dir, csv_name),
            os.path.join(lookups_base_dir, "blacklists", csv_name),
            os.path.join(lookups_base_dir, "whitelists", csv_name)
        ]

        # 3. Cerca ed elimina il file se esiste
        for csv_path in paths_to_check:
            if os.path.exists(csv_path):
                os.remove(csv_path)

        AdminExternalHandler.handleRemove(self, confInfo)