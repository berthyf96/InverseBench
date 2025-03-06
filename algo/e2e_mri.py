import torch
from .base import Algo

class End2EndMRI(Algo):
    def __init__(self, net, forward_op, mode):
        super(End2EndMRI, self).__init__(net, forward_op)
        self.mode = mode

    @torch.no_grad()
    def inference(self, observation, **kwargs):
        # ret = self.forward_op.normalize(self.net(observation, self.forward_op.mask.unsqueeze(-1)).double())
        # import matplotlib.pyplot as plt
        # plt.imsave('tmp.png', ret[0, 0].detach().cpu().numpy(), cmap='gray')
        # breakpoint()
        return self.forward_op.normalize(self.net(observation, self.forward_op.mask.unsqueeze(-1)).double())