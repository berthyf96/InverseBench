import torch
import tqdm
from .base import Algo
import numpy as np
import wandb
from utils.scheduler import Scheduler
    
class FPS(Algo):
    def __init__(self, 
                 net,
                 forward_op,
                 scheduler_config,
                 eta,
                 num_particles):
        super(FPS, self).__init__(net, forward_op)
        self.scheduler = Scheduler(**scheduler_config)
        self.eta = eta
        self.num_particles = num_particles

    def score(self, model, x, sigma):
        """
            Computes the score function for the given model.

            Parameters:
                model (DiffusionModel): Diffusion model.
                x (torch.Tensor): Input tensor.
                sigma (float): Sigma value.

            Returns:
                torch.Tensor: The computed score.
        """
        sigma = torch.as_tensor(sigma).to(x.device)
        d = model(x, sigma)
        return (d - x) / sigma**2
    
    
    @torch.no_grad()
    def inference(self, observation, num_samples=1, **kwargs):
        # NOTE: This implementation transforms linear inverse problems to its equivalent form of inpainting in the space of SVD.
        device = self.forward_op.device
        
        sigma_y = self.forward_op.sigma_noise
        sigma_y = max(sigma_y, 1e-3)
        observation_t = self.forward_op.Ut(observation)
        # 1. Generate y sequence (Algorithm 2)
        
        observations = []
        # z = torch.randn(observation.shape[0], self.net.img_channels, self.net.img_resolution, self.net.img_resolution, device=device) * self.scheduler.sigma_max
        z = torch.randn(observation.shape[0], *self.forward_op.M.shape, device=device) * self.scheduler.sigma_max
        y = self.forward_op.M * z
        observations.append(y * self.scheduler.scaling_steps[0])
        for k in range(self.scheduler.num_steps):
            sigma, sigma_next = self.scheduler.sigma_steps[k], self.scheduler.sigma_steps[k + 1]
            # DDIM update
            y = observation_t + np.sqrt(1 - self.eta **2) * sigma_next / sigma * (y - observation_t) + self.eta * sigma_next * torch.randn_like(y)
            observations.append(y * self.scheduler.scaling_steps[k+1])

        # 2. Generate x sequence (Algorithm 2)
        x_t = torch.stack([z]*self.num_particles, dim=1)
        pbar = tqdm.trange(self.scheduler.num_steps)
        for step in pbar:
            sigma, sigma_next = self.scheduler.sigma_steps[step], self.scheduler.sigma_steps[step + 1]
            x = self.forward_op.V(x_t)

            x0 = self.net(x.flatten(0,1)/self.scheduler.scaling_steps[step], torch.as_tensor(sigma).to(x.device)).view\
                (observation.shape[0], self.num_particles, self.net.img_channels, self.net.img_resolution, self.net.img_resolution)
            x0 = self.forward_op.S*self.forward_op.Vt(x0)
            x_next_t =  x0 + np.sqrt(1 - self.eta**2) * sigma_next / sigma * (x_t - x0)

            variance = (1/self.eta ** 2 / sigma_next ** 2 + self.forward_op.M / sigma_y ** 2 / self.scheduler.scaling_steps[step+1] ** 2) ** -1
            mean = x_next_t / (self.eta ** 2 * sigma_next ** 2) + self.forward_op.M * observations[step].unsqueeze(1) / (sigma_y ** 2 * self.scheduler.scaling_steps[step+1] ** 2)
            mean = variance * mean
            x_t = self.scheduler.scaling_steps[step+1]*(torch.randn_like(x_t) * torch.sqrt(variance) + mean)
            prob_y = -torch.linalg.norm((observations[step].unsqueeze(1) - self.forward_op.M * x_t).flatten(2), dim=-1) ** 2 / (2 * sigma_y ** 2 * self.scheduler.scaling_steps[step+1] ** 2)
            prob_x = -torch.linalg.norm((x_next_t - x_t).flatten(2), dim=-1) ** 2 / (2 * sigma_next ** 2 * self.eta ** 2)
            prob_prev = -torch.linalg.norm(((mean - x_t)/torch.sqrt(variance)).flatten(2), dim=-1) ** 2 / 2
            prob = prob_x + prob_y - prob_prev
            exp_prob = torch.exp(prob - prob.max(dim=1, keepdim=True)[0]).clip(min=-60)
            samples = torch.multinomial(exp_prob, self.num_particles, replacement=True)
            x_ts = []
            for i in range(samples.shape[0]):
                x_ts.append(x_t[i,samples[i,:]])
            x_t = torch.stack(x_ts, dim=0)
        return self.forward_op.V(x_t[:,0])


