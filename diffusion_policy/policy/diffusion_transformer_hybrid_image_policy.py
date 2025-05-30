from typing import Dict, Tuple, Optional
import dill
import math
import pathlib
import torch
import torch.nn as nn
import torch.nn.functional as F
from einops import rearrange, reduce
from diffusers.schedulers.scheduling_ddpm import DDPMScheduler

from diffusion_policy.model.common.normalizer import LinearNormalizer
from diffusion_policy.policy.base_image_policy import BaseImagePolicy
from diffusion_policy.model.diffusion.transformer_for_diffusion import TransformerForDiffusion
from diffusion_policy.model.diffusion.mask_generator import LowdimMaskGenerator
from diffusion_policy.common.robomimic_config_util import get_robomimic_config
from robomimic.algo import algo_factory
from robomimic.algo.algo import PolicyAlgo
import robomimic.utils.obs_utils as ObsUtils
import robomimic.models.base_nets as rmbn
import diffusion_policy.model.vision.crop_randomizer as dmvc
from diffusion_policy.common.pytorch_util import dict_apply, replace_submodules
import wandb
import numpy as np


def dct_2d(x):
    """
    2D Discrete Cosine Transform using matrix multiplication.
    """
    N = x.shape[-2]
    M = x.shape[-1]
    
    # Create DCT transform matrices
    u = torch.arange(N).float().view(1, -1).to(x.device)  # Row indices
    v = torch.arange(M).float().view(-1, 1).to(x.device)  # Column indices
    
    dct_matrix_row = torch.cos((2 * u + 1) * v * torch.pi / (2 * N))
    dct_matrix_col = torch.cos((2 * v + 1) * u * torch.pi / (2 * M))
    
    # Apply DCT transformation
    dct_out = torch.matmul(dct_matrix_row, x)
    dct_out = torch.matmul(dct_out, dct_matrix_col)
    
    return dct_out

def compress_image_with_dct(x):
    x = x.cuda()
    # x: (batch_size, 3, 70, 70)
    batch_size = x.shape[0]
    
    # Apply DCT to each channel
    dct_r = dct_2d(x[:, 0, :, :])
    dct_g = dct_2d(x[:, 1, :, :])
    dct_b = dct_2d(x[:, 2, :, :])
    
    # Keep top-left corner coefficients (8x8 from each channel)
    top_r = dct_r[:, :4, :4].flatten(start_dim=1)  # Shape: (batch_size, 64)
    top_g = dct_g[:, :4, :4].flatten(start_dim=1)  
    top_b = dct_b[:, :4, :4].flatten(start_dim=1)  
    
    # Concatenate and truncate to 64 elements
    compressed_vector = torch.cat([top_r, top_g, top_b], dim=1)#[:, :64]
    
    return compressed_vector

class DiffusionTransformerHybridImagePolicy(BaseImagePolicy):
    def __init__(self, 
            shape_meta: dict,
            noise_scheduler: DDPMScheduler,
            # task params
            horizon, 
            n_action_steps, 
            n_obs_steps,
            num_inference_steps=None,
            use_embed_if_present=True,
            # image
            crop_shape=(76, 76),
            obs_encoder_group_norm=False,
            eval_fixed_crop=False,
            # arch
            n_layer=8,
            n_cond_layers=0,
            n_head=4,
            n_emb=256,
            p_drop_emb=0.0,
            p_drop_attn=0.3,
            causal_attn=True,
            time_as_cond=True,
            obs_as_cond=True,
            pred_action_steps_only=False,
            # parameters passed to step
            past_action_pred=False,
            obs_encoder_dir=None,
            obs_encoder_freeze=False,
            past_steps_reg=-1,
            **kwargs):
        super().__init__()

        self.past_action_pred = past_action_pred
        self.use_embed_if_present = use_embed_if_present
        self.past_steps_reg = past_steps_reg
        # parse shape_meta
        action_shape = shape_meta['action']['shape']
        assert len(action_shape) == 1
        action_dim = action_shape[0]
        obs_shape_meta = shape_meta['obs']
        obs_config = {
            'low_dim': [],
            'rgb': [],
            'depth': [],
            'scan': []
        }
        obs_key_shapes = dict()
        for key, attr in obs_shape_meta.items():
            shape = attr['shape']
            obs_key_shapes[key] = list(shape)

            type = attr.get('type', 'low_dim')
            if type == 'rgb':
                obs_config['rgb'].append(key)
            elif type == 'low_dim':
                obs_config['low_dim'].append(key)
            else:
                raise RuntimeError(f"Unsupported obs type: {type}")

        # get raw robomimic config
        config = get_robomimic_config(
            algo_name='bc_rnn',
            hdf5_type='image',
            task_name='square',
            dataset_type='ph')
        
        with config.unlocked():
            # set config with shape_meta
            config.observation.modalities.obs = obs_config

            if crop_shape is None:
                for key, modality in config.observation.encoder.items():
                    if modality.obs_randomizer_class == 'CropRandomizer':
                        modality['obs_randomizer_class'] = None
            else:
                # set random crop parameter
                ch, cw = crop_shape
                for key, modality in config.observation.encoder.items():
                    if modality.obs_randomizer_class == 'CropRandomizer':
                        modality.obs_randomizer_kwargs.crop_height = ch
                        modality.obs_randomizer_kwargs.crop_width = cw

        # init global state
        ObsUtils.initialize_obs_utils_with_config(config)

        # load model
        policy: PolicyAlgo = algo_factory(
                algo_name=config.algo_name,
                config=config,
                obs_key_shapes=obs_key_shapes,
                ac_dim=action_dim,
                device='cpu',
            )

        obs_encoder = policy.nets['policy'].nets['encoder'].nets['obs']
        
        if obs_encoder_group_norm:
            # replace batch norm with group norm
            replace_submodules(
                root_module=obs_encoder,
                predicate=lambda x: isinstance(x, nn.BatchNorm2d),
                func=lambda x: nn.GroupNorm(
                    num_groups=x.num_features//16, 
                    num_channels=x.num_features)
            )
            # obs_encoder.obs_nets['agentview_image'].nets[0].nets
        
        # obs_encoder.obs_randomizers['agentview_image']
        if eval_fixed_crop:
            replace_submodules(
                root_module=obs_encoder,
                predicate=lambda x: isinstance(x, rmbn.CropRandomizer),
                func=lambda x: dmvc.CropRandomizer(
                    input_shape=x.input_shape,
                    crop_height=x.crop_height,
                    crop_width=x.crop_width,
                    num_crops=x.num_crops,
                    pos_enc=x.pos_enc
                )
            )

        # create diffusion model
        obs_feature_dim = obs_encoder.output_shape()[0]
        input_dim = action_dim if obs_as_cond else (obs_feature_dim + action_dim)
        output_dim = input_dim
        cond_dim = obs_feature_dim if obs_as_cond else 0

        model = TransformerForDiffusion(
            input_dim=input_dim,
            output_dim=output_dim,
            horizon=horizon,
            n_obs_steps=n_obs_steps,
            cond_dim=cond_dim,
            n_layer=n_layer,
            n_head=n_head,
            n_emb=n_emb,
            p_drop_emb=p_drop_emb,
            p_drop_attn=p_drop_attn,
            causal_attn=causal_attn,
            time_as_cond=time_as_cond,
            obs_as_cond=obs_as_cond,
            n_cond_layers=n_cond_layers
        )

        self.obs_encoder = obs_encoder
        self.model = model
        self.noise_scheduler = noise_scheduler
        self.mask_generator = LowdimMaskGenerator(
            action_dim=action_dim,
            obs_dim=0 if (obs_as_cond) else obs_feature_dim,
            max_n_obs_steps=n_obs_steps,
            fix_obs_steps=True,
            action_visible=False
        )
        self.normalizer = LinearNormalizer()
        self.horizon = horizon
        self.obs_feature_dim = obs_feature_dim
        self.action_dim = action_dim
        self.n_action_steps = n_action_steps
        self.n_obs_steps = n_obs_steps
        self.obs_as_cond = obs_as_cond
        self.pred_action_steps_only = pred_action_steps_only
        self.kwargs = kwargs

        if obs_encoder_dir:
            print(f"loading encoder from {obs_encoder_dir}")
            # obs_encoder_path = pathlib.Path(obs_encoder_dir)

            payload = torch.load(open(obs_encoder_dir, "rb"), pickle_module=dill)
            payload['state_dicts']['obs_encoder'] = {}
            for key, value in payload['state_dicts']['model'].items():
                if key.startswith("obs_encoder"):
                    # split keys
                    payload['state_dicts']['obs_encoder'][key[len('obs_encoder.'):]] = value
            self.obs_encoder.load_state_dict(payload['state_dicts']['obs_encoder'], **kwargs)
        if obs_encoder_freeze:
            print("freezing encoder")
            for param in self.obs_encoder.parameters():
                param.requires_grad = False


        if num_inference_steps is None:
            num_inference_steps = noise_scheduler.config.num_train_timesteps
        self.num_inference_steps = num_inference_steps
    
    # ========= inference  ============
    def conditional_sample(self, 
            condition_data, condition_mask,
            cond=None, generator=None, act=None,
            # keyword arguments to scheduler.step
            **kwargs
            ):
        model = self.model
        scheduler = self.noise_scheduler

        trajectory = torch.randn(
            size=condition_data.shape, 
            dtype=condition_data.dtype,
            device=condition_data.device,
            generator=generator)
    
        # set step values
        scheduler.set_timesteps(self.num_inference_steps)

        for t in scheduler.timesteps:
            # 1. apply conditioning
            trajectory[condition_mask] = condition_data[condition_mask]
            if act is not None:
                trajectory[:,:act.shape[1]] = act   

            # 2. predict model output
            model_output = model(trajectory, t, cond)

            # 3. compute previous image: x_t -> x_t-1
            trajectory = scheduler.step(
                model_output, t, trajectory, 
                generator=generator,
                **kwargs
                ).prev_sample
        
        # finally make sure conditioning is enforced
        trajectory[condition_mask] = condition_data[condition_mask]        

        return trajectory

    def embed_observation(self, obs_dict):

        """
        obs_dict: must include "obs" key
        result: must include "action" key
        """
        assert 'past_action' not in obs_dict # not implemented yet
        # normalize input
        nobs = self.normalizer.normalize(obs_dict)
        value = next(iter(nobs.values()))
        B, To = value.shape[:2]
        print(B, To, value.shape)

        # build input
        device = self.device
        dtype = self.dtype

        # handle different ways of passing observation
        this_nobs = dict_apply(nobs, lambda x: x[:,:To,...].reshape(-1,*x.shape[2:]))
        nobs_features = self.obs_encoder(this_nobs)
        # reshape back to B, To, Do
        cond = nobs_features.reshape(B, To, -1)

        return cond

    def embed_observation_dct(self, obs_dict):

        """
        obs_dict: must include "obs" key
        result: must include "action" key
        """
        assert 'past_action' not in obs_dict # not implemented yet
        # normalize input
        nobs = self.normalizer.normalize(obs_dict)
        value = next(iter(nobs.values()))
        B, To = value.shape[:2]
        print(B, To, value.shape)

        # build input
        device = self.device
        dtype = self.dtype

        # handle different ways of passing observation
        for key in nobs:
            x = nobs[key]
            x = x[:,:To,...].reshape(-1,*x.shape[2:])
            nobs[key] = x
        # this_nobs = dict_apply(nobs, lambda x: x[:,:To,...].reshape(-1,*x.shape[2:]))

        nobs_features = None
        # iterate over the images and pass them through the dct compressor
        camera_keys = ["agent_view", "wrist"]
        size = 0
        embedding = []
        print("here keys", nobs.keys())
        for key in nobs:
            if key in camera_keys:
                emb = compress_image_with_dct(nobs[key])
            else:
                emb = nobs[key]
                
            embedding.append(emb)
            size += emb.shape[1]
        
        B = emb.shape[0]
        n = 135 - size 
        embedding.append(torch.from_numpy(np.zeros((B, n))).cuda())
        # the rest are concatenated to the obs
        nobs_features = torch.hstack(embedding)
        # reshape back to B, To, Do
        cond = nobs_features.reshape(B, To, -1)

        return cond


    def predict_action(self, obs_dict: Dict[str, torch.Tensor], act_cond: Optional[torch.Tensor] = None) -> Dict[str, torch.Tensor]:
        """
        obs_dict: must include "obs" key
        result: must include "action" key
        """
        assert 'past_action' not in obs_dict # not implemented yet
        # normalize input
        nobs = self.normalizer.normalize(obs_dict)
        if "embedding" in obs_dict:
            nobs["embedding"] = obs_dict["embedding"]
        value = next(iter(nobs.values()))
        B, To = value.shape[:2]
        T = self.horizon
        Da = self.action_dim
        Do = self.obs_feature_dim
        To = self.n_obs_steps

        # build input
        device = self.device
        dtype = self.dtype


        # handle different ways of passing observation
        cond = None
        cond_data = None
        cond_mask = None
        if self.obs_as_cond:
            if self.use_embed_if_present and "embedding" in obs_dict:
                cond = obs_dict["embedding"]
            else:
                this_nobs = dict_apply(nobs, lambda x: x[:,:To,...].reshape(-1,*x.shape[2:]))
                nobs_features = self.obs_encoder(this_nobs)
                # reshape back to B, To, Do
                cond = nobs_features.reshape(B, To, -1)
            shape = (B, T, Da)
            if self.pred_action_steps_only:
                shape = (B, self.n_action_steps, Da)
            cond_data = torch.zeros(size=shape, device=device, dtype=dtype)
            cond_mask = torch.zeros_like(cond_data, dtype=torch.bool)
        else:
            # condition through impainting
            this_nobs = dict_apply(nobs, lambda x: x[:,:To,...].reshape(-1,*x.shape[2:]))
            nobs_features = self.obs_encoder(this_nobs)
            # reshape back to B, To, Do
            nobs_features = nobs_features.reshape(B, To, -1)
            shape = (B, T, Da+Do)
            cond_data = torch.zeros(size=shape, device=device, dtype=dtype)
            cond_mask = torch.zeros_like(cond_data, dtype=torch.bool)
            cond_data[:,:To,Da:] = nobs_features
            cond_mask[:,:To,Da:] = True

        if act_cond is not None:
            act_cond = self.normalizer['action'].normalize(act_cond)

        # run sampling
        nsample = self.conditional_sample(
            cond_data, 
            cond_mask,
            cond=cond,
            act=act_cond,
            **self.kwargs)
        
        # unnormalize prediction
        naction_pred = nsample[...,:Da]
        action_pred = self.normalizer['action'].unnormalize(naction_pred)

        # get action
        if self.pred_action_steps_only:
            action = action_pred
        else:
            start = To - 1
            end = start + self.n_action_steps
            action = action_pred[:,start:end]
        
        result = {
            'action': action,
            'action_pred': action_pred
        }
        return result

    # ========= training  ============
    def set_normalizer(self, normalizer: LinearNormalizer):
        self.normalizer.load_state_dict(normalizer.state_dict())

    def get_optimizer(
            self, 
            transformer_weight_decay: float, 
            obs_encoder_weight_decay: float,
            learning_rate: float, 
            betas: Tuple[float, float]
        ) -> torch.optim.Optimizer:
        optim_groups = self.model.get_optim_groups(
            weight_decay=transformer_weight_decay)
        optim_groups.append({
            "params": self.obs_encoder.parameters(),
            "weight_decay": obs_encoder_weight_decay
        })
        optimizer = torch.optim.AdamW(
            optim_groups, lr=learning_rate, betas=betas
        )
        return optimizer

    def compute_loss(self, batch, debug=False):
        # normalize input
        assert 'valid_mask' not in batch
        nobs = self.normalizer.normalize(batch['obs'])
        nactions = self.normalizer['action'].normalize(batch['action'])
        batch_size = nactions.shape[0]
        horizon = nactions.shape[1]
        To = self.n_obs_steps

        # handle different ways of passing observation
        cond = None
        trajectory = nactions
        if self.obs_as_cond:
            # reshape B, T, ... to B*T
            if self.use_embed_if_present and "embedding" in batch["obs"]:
                cond = batch["obs"]["embedding"]
            else:
                this_nobs = dict_apply(nobs, 
                    lambda x: x[:,:To,...].reshape(-1,*x.shape[2:]))
                nobs_features = self.obs_encoder(this_nobs)
                # reshape back to B, T, Do
                cond = nobs_features.reshape(batch_size, To, -1)
            if self.pred_action_steps_only:
                start = To - 1
                end = start + self.n_action_steps
                trajectory = nactions[:,start:end]
        else:
            # reshape B, T, ... to B*T
            this_nobs = dict_apply(nobs, lambda x: x.reshape(-1, *x.shape[2:]))
            nobs_features = self.obs_encoder(this_nobs)
            # reshape back to B, T, Do
            nobs_features = nobs_features.reshape(batch_size, horizon, -1)
            trajectory = torch.cat([nactions, nobs_features], dim=-1).detach()

        # generate impainting mask
        if self.pred_action_steps_only:
            condition_mask = torch.zeros_like(trajectory, dtype=torch.bool)
        else:
            condition_mask = self.mask_generator(trajectory.shape)

        # Sample noise that we'll add to the images
        noise = torch.randn(trajectory.shape, device=trajectory.device)
        bsz = trajectory.shape[0]
        # Sample a random timestep for each image
        timesteps = torch.randint(
            0, self.noise_scheduler.config.num_train_timesteps, 
            (bsz,), device=trajectory.device
        ).long()
        # Add noise to the clean images according to the noise magnitude at each timestep
        # (this is the forward diffusion process)
        noisy_trajectory = self.noise_scheduler.add_noise(
            trajectory, noise, timesteps)

        # compute loss mask
        loss_mask = ~condition_mask

        # apply conditioning
        noisy_trajectory[condition_mask] = trajectory[condition_mask]
        
        # Predict the noise residual
        pred = self.model(noisy_trajectory, timesteps, cond)

        pred_type = self.noise_scheduler.config.prediction_type 
        if pred_type == 'epsilon':
            target = noise
        elif pred_type == 'sample':
            target = trajectory
        else:
            raise ValueError(f"Unsupported prediction type {pred_type}")

        # val = self.horizon - self.n_obs_steps
        if not self.past_action_pred:
            # val = self.horizon - self.n_obs_steps
            pred = pred[:, self.n_obs_steps-1:]
            if debug:
                print(pred.shape[1], target.shape[1])
            target = target[:, self.n_obs_steps-1:]
            loss_mask = loss_mask[:, self.n_obs_steps-1:]
        if self.past_steps_reg != -1:
            # print(self.n_obs_steps, self.past_steps_reg)
            assert self.n_obs_steps - self.past_steps_reg - 1 > 0
            pred = pred[:, self.n_obs_steps - self.past_steps_reg - 1:]
            # print(pred.shape)
            # breakpoint()
            target = target[:, self.n_obs_steps - self.past_steps_reg - 1:]
            loss_mask = loss_mask[:, self.n_obs_steps - self.past_steps_reg - 1:]

        loss = F.mse_loss(pred, target, reduction='none')
        loss = loss * loss_mask.type(loss.dtype)
        loss = reduce(loss, 'b ... -> b (...)', 'mean')
        loss = loss.mean()
        return loss
