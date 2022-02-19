from brownie import accounts
import utils
setting_item = [
    "batchSize",
    "learningRate",
    "epochs",
    "nParticipators",
]
class MockInvoker(object):
    def __init__(self,setting) :
        self.contract = setting['contract']
        self.account = setting['account']
    def get_setting(self):
        setting_list = self.contract.setting({"from":self.account})
        assert len(setting_list) == 4
        setting_map = {
            'batchSize':setting_list[0],
            'learningRate':float(setting_list[1]),
            'epochs':setting_list[2],
            'nParticipators':setting_list[3],
        }
        return setting_map

    def get_global_model(self):
        bytes_model_param,lastestVersion = self.contract.getGlobalModel({"from":self.account})
        # transfer from type [HexStr] to type [bytes]
        bytes_model_param = utils.hex2bytes(bytes_model_param)
        return bytes_model_param,lastestVersion

    def get_model_updates(self):
        model_update_list = self.contract.getModelUpdates({"from":self.account})
        assert isinstance(model_update_list,list)
        format_model_updates = []
        for model_update in model_update_list:
            model_info = {
                "uploader":model_update[0],
                "train_size":model_update[1],
                "version":model_update[2],
                "bytes_model":utils.hex2bytes(model_update[3])
            }
            format_model_updates.append(model_info)
        return format_model_updates

    def upload_aggregation(self,aggregated_model):
        assert isinstance(aggregated_model,bytes)
        self.contract.uploadAggregation(aggregated_model,{"from":self.account})

    def upload_model_update(self,data_size,update_model):
        assert isinstance(update_model,bytes)
        self.contract.uploadModelUpdate(data_size,update_model,{"from":self.account})
    
    