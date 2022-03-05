import torch
import client_module.model  as model
from client_module.log import logger as l
from torch.utils.data import DataLoader
from torch.utils.data import TensorDataset
import pickle
import hashlib
from typing import Dict, Tuple, Sequence

class Trainer(object):
    def __init__(self,train_setting:dict):
        # l.debug(f"type of train_setting is {type(train_setting)}")
        assert isinstance(train_setting,dict)
        # training setting
        self.epochs = train_setting['epochs']
        self.batch_size = train_setting['batch_size']
        self.model_name = train_setting['model_name']
        self.learning_rate = float(train_setting['learning_rate'])
        self.train_ds = train_setting['dataset']
        assert isinstance(self.train_ds,TensorDataset)
        # init training model
        self.model = model.get_model(self.model_name)
        self.dev = torch.device('cpu')
        if torch.cuda.is_available():
            l.info(f'use cuda as dev')
            self.dev = torch.device('cuda')
        if torch.cuda.device_count() > 1:
            self.model = torch.nn.DataParallel(self.model)
        self.model = self.model.to(self.dev)
        self.opti = model.get_opti(self.model,self.learning_rate)
        self.loss_fn = model.get_loss_fn()
        # init dataloader
        self.train_dl = DataLoader(self.train_ds,batch_size= self.batch_size,shuffle=True)
         
    def load_bytes_model(self,bytes_model:bytes):
        assert isinstance(bytes_model,bytes)
        model_param_dict = pickle.loads(bytes_model)
        # l.debug(f"load model param,{type(model_param_dict)}")
        self._load_model(model_param_dict)

    def get_bytes_model(self)->bytes:
        model_param_dict = self.model.state_dict()
        # transfer obj to bytes
        bytes_model = pickle.dumps(model_param_dict)
        return bytes_model

    def get_data_size(self)->int:
        return len(self.train_dl)

    def get_model_abstract(self)->str:
        m = hashlib.md5()
        m.update(self.get_bytes_model())
        return m.hexdigest()

    def _load_model(self,model_params_dict:dict):
        self.model.load_state_dict(model_params_dict,strict=True)

    def local_training(self):
        for epoch in range(self.epochs):
            for train_x, train_y in self.train_dl:
                train_x, train_y = train_x.to(self.dev), train_y.to(self.dev)
                self.opti.zero_grad()
                pred_y = self.model(train_x)
                loss = self.loss_fn(pred_y, train_y)
                loss.backward()
                self.opti.step()
        
    def evaluate(self,test_dl:DataLoader)->Tuple[float,float]:
        sum_accu = 0
        num = 0
        running_loss = 0.0
        with torch.no_grad():
            for test_x, test_y in test_dl:
                # get batch test_x & batch test_y
                
                if hasattr(torch.cuda, 'empty_cache'):
                    torch.cuda.empty_cache()
                test_x, test_y = test_x.to(self.dev), test_y.to(self.dev)
                pred = self.model(test_x)
                loss = self.loss_fn(pred,test_y)
                running_loss += loss
                pred = torch.argmax(pred, dim=1)
                sum_accu += (pred == test_y).float().mean()
                num += 1
            running_loss /= num
            accuary = sum_accu/num
            return accuary.item(),running_loss.item()
    
    def aggregate(self,update_models:list)->bytes:
        # [ (data_size_1,bytes_model_1) , .... , (data_size_n,bytes_model_n) ]
        if len(update_models) == 0:
            return pickle.dumps(self.model.state_dict())
        average_params = None
        all_data_size = 0
        for update_info in update_models:
            all_data_size  = all_data_size + update_info['train_size']
        for update_info in update_models:
            # model_info = {
            #     "uploader":
            #     "train_size":
            #     "version":
            #     "bytes_model":
            #     "bytes_model_hash"
            # }
            data_size = update_info['train_size']
            bytes_model = update_info['bytes_model']
            uploader = update_info['uploader']
            model_dict = pickle.loads(bytes_model)
            fraction = (float(data_size) / float(all_data_size))
            l.debug(f'fraction of uploader {uploader} is {fraction},data_size is {data_size}')
            if average_params is None:
                average_params = {}
                for k,v in  model_dict.items():
                    average_params[k] = v.clone() * fraction
            else:
                for k in average_params:
                    average_params[k] = average_params[k] + model_dict[k] * fraction
        # bytes
        bytes_aggregate_model = pickle.dumps(average_params)
        return bytes_aggregate_model


