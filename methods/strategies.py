from typing import Optional, List

import numpy as np
from avalanche.training import BaseStrategy
from avalanche.training.plugins import StrategyPlugin, EvaluationPlugin
from avalanche.training.plugins.evaluation import default_logger
from torch import nn
from torch.nn.modules.batchnorm import _BatchNorm
from torch.optim import Optimizer
from torch.utils.data import DataLoader

from methods.plugins.cml import ContinualMetricLearningPlugin, \
    BatchNormModelWrap, DropContinualMetricLearningPlugin, \
    ClassIncrementalBatchNormModelWrap
from methods.plugins.er import EmbeddingRegularizationPlugin
from methods.plugins.hal import AnchorLearningPlugin
from methods.plugins.ewc import EWCCustomPlugin
from models.utils import CombinedModel


class CustomSubset:
    def __init__(self, dataset, indices) -> None:
        self._dataset = dataset
        self.indices = indices

    def __getitem__(self, idx):
        if isinstance(idx, list):
            return self.dataset[[self.indices[i] for i in idx]]
        return self.dataset[self.indices[idx]]

    def __len__(self):
        return len(self.indices)

    @property
    def dataset(self):
        return self._dataset

    def __getattr__(self, item):
        if item == 'dataset':
            a = getattr(self, item)
        else:
            a = getattr(self.dataset, item)
        return a


class EmbeddingRegularization(BaseStrategy):

    def __init__(self,
                 feature_extractor: nn.Module,
                 classifier: nn.Module,
                 model: CombinedModel,
                 optimizer: Optimizer, criterion,
                 mem_size: int,
                 penalty_weight: float,
                 train_mb_size: int = 1,
                 train_epochs: int = 1,
                 eval_mb_size: int = None,
                 device=None,
                 plugins: Optional[List[StrategyPlugin]] = None,
                 evaluator: EvaluationPlugin = default_logger,
                 eval_every=-1):

        for name, module in feature_extractor.named_modules():
            if isinstance(module, _BatchNorm):
                feature_extractor = BatchNormModelWrap(feature_extractor)
                break

        model = CombinedModel(feature_extractor, classifier)

        rp = EmbeddingRegularizationPlugin(mem_size, penalty_weight)
        if plugins is None:
            plugins = [rp]
        else:
            plugins.append(rp)

        super().__init__(
            model, optimizer, criterion,
            train_mb_size=train_mb_size,
            train_epochs=train_epochs,
            eval_mb_size=eval_mb_size, device=device,
            plugins=plugins,
            evaluator=evaluator, eval_every=eval_every)


class ContinualMetricLearning(BaseStrategy):

    def __init__(self, model: CombinedModel, dev_split_size: float,
                 optimizer: Optimizer, criterion, penalty_weight: float,
                 train_mb_size: int = 1, train_epochs: int = 1, proj_w=1,
                 eval_mb_size: int = None, device=None,
                 sit: bool = False, num_experiences: int = 20,
                 sit_memory_size: int = 200,
                 plugins: Optional[List[StrategyPlugin]] = None,
                 evaluator: EvaluationPlugin = default_logger, eval_every=-1):

        # if sit:
        #     rp = ClassIncrementalContinualMetricLearningPlugin(penalty_weight, sit)
        # else:

        # if any(isinstance(module, _BatchNorm) for module in
        #        model.modules()) and not sit:
        #     # for name, module in model.named_modules():
        #     #     if isinstance(module, _BatchNorm):
        #     model = BatchNormModelWrap(model)
        #     # break

        if any(isinstance(module, _BatchNorm) for module in
               model.modules()):
            # for name, module in model.named_modules():
            #     if isinstance(module, _BatchNorm):
            if sit:
                pass
                # model = ClassIncrementalBatchNormModelWrap(model)
            else:
                model = BatchNormModelWrap(model)
            # break

        # rp = ContinualMetricLearningPlugin(penalty_weight, sit,
        #                                    num_experiences=num_experiences,
        #                                    sit_memory_size=sit_memory_size)

        rp = DropContinualMetricLearningPlugin(penalty_weight, sit,
                                               proj_w=proj_w,
                                               num_experiences=num_experiences,
                                               sit_memory_size=sit_memory_size)

        self.rp = rp

        if plugins is None:
            plugins = [rp]
        else:
            plugins.append(rp)

        self.dev_split_size = dev_split_size
        self.dev_dataloader = None
        self.dev_indexes = dict()

        super().__init__(
            model, optimizer, criterion,
            train_mb_size=train_mb_size,
            train_epochs=train_epochs,
            eval_mb_size=eval_mb_size, device=device,
            plugins=plugins,
            evaluator=evaluator, eval_every=eval_every)

    # def eval_dataset_adaptation(self, **kwargs):
    #     """ Initialize `self.adapted_dataset`. """
    #     self.train_dataset_adaptation()
    # self.adapted_dataset = self.experience.dataset
    # self.adapted_dataset = self.adapted_dataset.eval()

    def train_dataset_adaptation(self, **kwargs):
        """ Initialize `self.adapted_dataset`. """

        exp_n = self.experience.current_experience

        if not hasattr(self.experience, 'dev_dataset'):
            dataset = self.experience.dataset
            idx = np.arange(len(dataset))
            np.random.shuffle(idx)

            if isinstance(self.dev_split_size, int):
                dev_i = self.dev_split_size
            else:
                dev_i = int(len(idx) * self.dev_split_size)

            dev_idx = idx[:dev_i]
            train_idx = idx[dev_i:]
            self.dev_indexes[exp_n] = (train_idx, dev_idx)

            self.experience.dataset = CustomSubset(dataset.train(), train_idx)
            self.experience.dev_dataset = CustomSubset(dataset.eval(), dev_idx)

        # if exp_n not in self.dev_indexes:
        #     train = self.experience.dataset
        #     idx = np.arange(len(train))
        #     np.random.shuffle(idx)
        #     dev_i = int(len(idx) * self.dev_split_size)
        #
        #     dev_idx = idx[:dev_i]
        #     train_idx = idx[dev_i:]
        #     self.dev_indexes[exp_n] = (train_idx, dev_idx)
        #
        #     dataset = self.experience.dataset
        #     self.experience.dataset = CustomSubset(dataset.train(), train_idx)
        #     self.experience.dev_dataset = CustomSubset(dataset.eval(), dev_idx)
        # else:
        #     train_idx, dev_idx = self.dev_indexes[exp_n]

        self.adapted_dataset = self.experience.dataset
        # self.adapted_dataset = self.adapted_dataset.train()

    # def make_train_dataloader(self, num_workers=0, shuffle=True,
    #                           pin_memory=True, **kwargs):
    #
    #     exp_n = self.experience.current_experience
    #     if exp_n not in self.dev_indexes:
    #         train = self.experience.dataset
    #         idx = np.arange(len(train))
    #         np.random.shuffle(idx)
    #         dev_i = int(len(idx) * self.dev_split_size)
    #
    #         dev_idx = idx[:dev_i]
    #         train_idx = idx[dev_i:]
    #         self.dev_indexes[exp_n] = (train_idx, dev_idx)
    #     else:
    #         train_idx, dev_idx = self.dev_indexes[exp_n]
    #
    #     self.dataloader = DataLoader(Subset(self.adapted_dataset, train_idx),
    #                                  num_workers=num_workers,
    #                                  batch_size=self.train_mb_size,
    #                                  shuffle=shuffle,
    #                                  pin_memory=pin_memory)
    #
    #     self.dev_dataloader = DataLoader(Subset(self.adapted_dataset.eval(),
    #                                             dev_idx),
    #                                      num_workers=num_workers,
    #                                      batch_size=self.train_mb_size,
    #                                      shuffle=shuffle,
    #                                      pin_memory=pin_memory)

    def criterion(self):
        """ Loss function. """
        loss = self.rp.loss(self)
        return loss

    def forward(self):
        res = super().forward()
        if not self.model.training:
            res = self.rp.calculate_classes(self, res)
        return res


class AnchorLearning(BaseStrategy):
    def __init__(self,
                 feature_extractor: nn.Module,
                 classifier: nn.Module,
                 optimizer: Optimizer, criterion,
                 ring_size: int,
                 lamb: float,
                 beta: float,
                 alpha: float,
                 embedding_strength: float,
                 k: int = 100,
                 train_mb_size: int = 1, train_epochs: int = 1,
                 eval_mb_size: int = None, device=None,
                 plugins: Optional[List[StrategyPlugin]] = None,
                 evaluator: EvaluationPlugin = default_logger, eval_every=-1,
                 **kwargs):

        model = CombinedModel(feature_extractor,
                              classifier=classifier)

        rp = AnchorLearningPlugin(ring_size=ring_size,
                                  regularization=lamb,
                                  decay_rate=beta,
                                  lr=alpha,
                                  embedding_strength=embedding_strength,
                                  k=k)
        self.rp = rp

        if plugins is None:
            plugins = [rp]
        else:
            plugins.append(rp)

        super().__init__(
            model, optimizer, criterion,
            train_mb_size=train_mb_size,
            train_epochs=train_epochs,
            eval_mb_size=eval_mb_size, device=device,
            plugins=plugins,
            evaluator=evaluator, eval_every=eval_every)


class CustomEWC(BaseStrategy):
    """ Elastic Weight Consolidation (EWC) strategy.

    See EWC plugin for details.
    This strategy does not use task identities.
    """

    def __init__(self, model, optimizer: Optimizer, criterion,
                 ewc_lambda: float, mode: str = 'separate',
                 decay_factor: Optional[float] = None,
                 keep_importance_data: bool = False,
                 train_mb_size: int = 1, train_epochs: int = 1,
                 eval_mb_size: int = None, device=None,
                 plugins: Optional[List[StrategyPlugin]] = None,
                 evaluator: EvaluationPlugin = default_logger, eval_every=-1):
        """ Init.

        :param model: The model.
        :param optimizer: The optimizer to use.
        :param criterion: The loss criterion to use.
        :param ewc_lambda: hyperparameter to weigh the penalty inside the total
               loss. The larger the lambda, the larger the regularization.
        :param mode: `separate` to keep a separate penalty for each previous
               experience. `onlinesum` to keep a single penalty summed over all
               previous tasks. `onlineweightedsum` to keep a single penalty
               summed with a decay factor over all previous tasks.
        :param decay_factor: used only if mode is `onlineweightedsum`.
               It specify the decay term of the importance matrix.
        :param keep_importance_data: if True, keep in memory both parameter
                values and importances for all previous task, for all modes.
                If False, keep only last parameter values and importances.
                If mode is `separate`, the value of `keep_importance_data` is
                set to be True.
        :param train_mb_size: The train minibatch size. Defaults to 1.
        :param train_epochs: The number of training epochs. Defaults to 1.
        :param eval_mb_size: The eval minibatch size. Defaults to 1.
        :param device: The device to use. Defaults to None (cpu).
        :param plugins: Plugins to be added. Defaults to None.
        :param evaluator: (optional) instance of EvaluationPlugin for logging
            and metric computations.
        :param eval_every: the frequency of the calls to `eval` inside the
            training loop. -1 disables the evaluation. 0 means `eval` is called
            only at the end of the learning experience. Values >0 mean that
            `eval` is called every `eval_every` epochs and at the end of the
            learning experience.
        """
        ewc = EWCCustomPlugin(ewc_lambda, mode, decay_factor, keep_importance_data)
        if plugins is None:
            plugins = [ewc]
        else:
            plugins.append(ewc)

        super().__init__(
            model, optimizer, criterion,
            train_mb_size=train_mb_size, train_epochs=train_epochs,
            eval_mb_size=eval_mb_size, device=device, plugins=plugins,
            evaluator=evaluator, eval_every=eval_every)
