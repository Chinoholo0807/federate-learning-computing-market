import os
import sys
import copy
import logging
import pandas as pd
import numpy as np
import time
from typing import Dict, Tuple, Sequence
sys.path.append('.')
sys.path.append('..')
from brownie import accounts, ModelTrain, network
from client_module.log import logger as l, init_logging
from scripts.deploy import  deploy_contract,train_setting,task_setting
import client_module.utils as u
from client_module.client import MockClient
from torch.utils.data import DataLoader
from torch.utils.data import TensorDataset

simulator_setting = {}
for k in train_setting.keys():
    simulator_setting[k]=train_setting[k]
for k in task_setting.keys():
    simulator_setting[k]=task_setting[k]
simulator_setting[
    'report_dir'] = r'D:\cs\Code\VisualStudioCode\federate-learning-computing-market\federate_learning_with_blockchain\client_module\reports'
simulator_setting[
    'dataset_dir'] = r'D:\cs\Code\VisualStudioCode\federate-learning-computing-market\federate_learning_with_blockchain\client_module\data'
simulator_setting['log_dir'] = os.path.join(simulator_setting['report_dir'], 'logs')
simulator_setting['results_dir'] = os.path.join(simulator_setting['report_dir'], 'results')


n_attacker = 4
aggreagate_method = 'fed_avg'
# aggreagate_method = 'fed_vote_avg'

class ClusterSimulator(object):

    def __init__(self):
        log_dir = simulator_setting['log_dir']
        init_logging(log_dir, log_level=logging.DEBUG)
        l.info('aggreate_method = {am}, n_attacker = {na}, dataset = {ds}, model_name = {mn}, epochs= {ep}, n_vote= {nv}'.format(
            am = aggreagate_method,
            na = n_attacker,
            ds = simulator_setting['dataset_description'],
            mn = simulator_setting['model_description'],
            ep = simulator_setting['epochs'],
            nv = simulator_setting['n_vote'],
        ))
        dataset_dir = simulator_setting['dataset_dir']
        self.attackers = np.arange(n_attacker)
        self.accounts = accounts
        self.n_client = len(self.accounts)
        self.n_attacker = n_attacker
        self.n_participator = train_setting['n_participator']
        self.n_vote = train_setting['n_vote']
        self.model_name = task_setting['model_description']
        client_train_dataset,test_x_tensor,test_y_tensor = u.build_dataset(
            dataset_name=task_setting['dataset_description'],n_client=self.n_client,
            n_attacker=self.n_attacker,data_dir=simulator_setting['dataset_dir'])
        

        self.test_dl = DataLoader(TensorDataset(
            test_x_tensor, test_y_tensor), batch_size=5, shuffle=False)

        l.info(f"load test_dl(type DataLoader) finish...")

        self.contract = deploy_contract()
        l.info(f"deploy contract,contract's info:{self.contract}")

        self.round = 0
        self.train_result = []

        self.client_setting = copy.deepcopy(simulator_setting)
        self.clients = []
        for id in range(len(self.accounts)):
            custume_setting = copy.deepcopy(self.client_setting)
            custume_setting["model_name"] = self.model_name
            custume_setting['aggreagate_method'] = aggreagate_method
            custume_setting["ipfs_api"] = "/ip4/127.0.0.1/tcp/5001"
            train_x_tensor, train_y_tensor = client_train_dataset[id]
            custume_setting["dataset"] = TensorDataset(
                train_x_tensor, train_y_tensor)
            custume_setting["id"] = id
            custume_setting["account"] = self.accounts[id]
            custume_setting["contract"] = self.contract
            
            new_client = MockClient(custume_setting)
            del custume_setting
            self.clients.append(new_client)
        l.info(f"build {len(self.accounts)} clients finish")

    def flesh_clients_model(self, client_ids=None):
        l.info('[flesh_clients_model]')
        selected_clients = []
        if client_ids is None:
            selected_clients = self.clients
        else:
            for c_id in client_ids:
                selected_clients.append(self.clients[c_id])
        for client in selected_clients:
            client.flesh_global_model()

    def clients_local_train(self, client_ids=None):
        l.info('[clients_local_train]')
        selected_clients = []
        if client_ids is None:
            selected_clients = self.clients
        else:
            for c_id in client_ids:
                selected_clients.append(self.clients[c_id])
        for client in selected_clients:
            client.local_train()
            client.upload_model_update()

    def clients_local_evaluate(self, client_ids=None) -> list:
        l.info('[clients_local_evaluate]')
        selected_clients = []
        if client_ids is None:
            selected_clients = self.clients
        else:
            for c_id in client_ids:
                selected_clients.append(self.clients[c_id])
        local_acc = []
        for client in selected_clients:
            c_acc,_ = client.evaluate(self.test_dl)
            local_acc.append(c_acc)
            l.info("client %d local accuracy is %.4f",client.id,c_acc)
            l.debug(f"model view {client.model_view()}")
        return local_acc

    def evaluate_global_model(self) -> Tuple[float,float]:
        l.info('[evaluate_global_model]')
        self.clients[0].flesh_global_model()
        acc,loss = self.clients[0].evaluate(self.test_dl)
        l.info("round %d,global accuracy %.4f,global loss %.4f",self.round,acc,loss)
        l.debug(f"model view {self.clients[0].model_view()}")
        return acc,loss

    def client_vote(self,client_ids= None):
        l.info('[client vote]')
        selected_clients = []
        if client_ids is None:
            selected_clients = self.clients
        else:
            for c_id in client_ids:
                selected_clients.append(self.clients[c_id])
        for client in selected_clients:
            client.vote()

    def simulate_sequential(self, n=1,fixed_attacker=-1):
        # loop n times
        # the first round should upload init model,specific handle
        if self.round == 0:
            l.info(f'--------{self.round}--------')
            self.clients[0].init_model()
            # evalute init model loss
            global_acc,global_loss = self.evaluate_global_model()
            round_result = [self.round, global_acc,global_loss] + [0 for _ in range(self.n_participator)]
            self.train_result.append(round_result)
            self.round += 1
            n -= 1
        np.random.seed((24 * self.round) % 125)
        
        for r in range(n):
            client_ids = None
            # number of attacker in participators is fixed
            if not fixed_attacker == -1:
                n_normal = self.n_client - self.n_attacker
                order_attacker = np.random.permutation(self.n_attacker)[:fixed_attacker]
                order_normal = (np.random.permutation(n_normal) + n_attacker)[:self.n_participator-fixed_attacker]
                client_ids = np.hstack([order_attacker,order_normal]) 
            # random choice
            else:
                order = np.random.permutation(len(self.clients))
                client_ids = order[0:self.n_participator]
            l.info(f'--------{self.round}--------')
            l.info(f'select clients:{client_ids}')
            # participators flesh local model with global model
            self.flesh_clients_model(client_ids)
            # self.clients_local_evaluate(client_ids)
            # participators start local training
            self.clients_local_train(client_ids)
            # evaluate local  models
            local_acc = self.clients_local_evaluate(client_ids)
            # vote
            self.client_vote(client_ids)
            # evaluate global model
            global_acc ,global_loss= self.evaluate_global_model()
            round_result = [self.round, global_acc,global_loss] + local_acc
            self.train_result.append(round_result)
            self.round += 1

    def save_result(self):
        df = pd.DataFrame(self.train_result,
                          columns=['round', 'global_acc','global_loss'] + [f'local_acc{i}' for i in range(self.n_participator)],
                          dtype=float
                          )
        csv_name = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(time.time())) + \
                   '@npart{}_lr{}_bs{}_ep{}_{}_{}.csv'.format(train_setting['n_participator'],
                                                    train_setting['learning_rate'],
                                                    train_setting['batch_size'],
                                                    train_setting['epochs'],
                                                    self.model_name,
                                                    aggreagate_method)
        csv_path = os.path.join(simulator_setting['results_dir'],
                                csv_name)
        df.to_csv(csv_path,index=False)
