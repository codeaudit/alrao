import torch
import torch.nn as nn
import torch.optim as optim
from switch import Switch


class AlraoModel(nn.Module):
    r"""
    Arguments:
        model: model to train, given without its last layer
        nclassifiers: number of classifiers
        nclasses: number of classes
        classifier: python class to use to construct the classifiers
    """
    def __init__(self, model, nclassifiers, classifier, *args, **kwargs):
        super(AlraoModel, self).__init__()
        self.switch = Switch(nclassifiers, save_cl_perf=True)
        #self.model = VGGNet(args.size_multiplier)
        self.model = model #
        self.nclassifiers = nclassifiers

        for i in range(nclassifiers):
            U_classifier = classifier(*args, **kwargs)
            setattr(self, "classifier" + str(i), U_classifier)

    def method_fwd_model(self, method_name_src, method_name_dst = None):
        if method_name_dst is None:
            method_name_dst = method_name_src
        assert getattr(self, method_name_dst, None) is None, 'The method "' + method_name_dst + '" cannot be forwarded: an attribute with the same name already exists.'
        method = getattr(self.model, method_name_src)
        def f(*args, **kwargs):
            return method(*args, **kwargs)
        f.__doc__ = method.__doc__
        f.__name__ = method_name_dst
        setattr(self, f.__name__, f)

    def method_fwd_classifiers(self, method_name_src, method_name_dst = None):
        if method_name_dst is None:
            method_name_dst = method_name_src
        assert getattr(self, method_name_src, None) is None, 'The method "' + method_name_dst + '" cannot be forwarded: an attribute with the same name already exists.'
        lst_methods = []
        for i in range(self.nclassifiers):
            current_classifier = getattr(self, 'classifier' + str(i))
            lst_methods.append(getattr(current_classifier, method_name_src))

        def f(*args, **kwargs):
            ret = []
            for i in range(self.nclassifiers):
                ret.append(lst_methods[i](*args, **kw_args))
            return ret

        f.__doc__ = method.__doc__
        f.__name__ = method_name_dst
        setattr(self, f.__name__, f)

    def reset_parameters(self):
        self.model.reset_parameters()
        for i in range(self.nclassifiers):
            getattr(self, "classifier"+str(i)).reset_parameters()

    def forward(self, *args, **kwargs):
        r"""
        input x -> x = self.model(x)
        either 'x' is a scalar or a tuple:
            - 'x' is a scalar: 'x' is used as input of each classifier
            - 'x' is a tuple: 'x[0]' is used as input of each classifier
        """
        x = self.model(*args, **kwargs)
        if isinstance(x, tuple):
            x0 = x[0]
            lst_logpx = [cl(x0) for cl in self.classifiers()]
            self.last_x, self.last_lst_logpx = x0, lst_logpx
            return (self.switch.forward(lst_logpx),) + x[1:]
        else:
            lst_logpx = [cl(x) for cl in self.classifiers()]
            self.last_x, self.last_lst_logpx = x, lst_logpx
            return self.switch.forward(lst_logpx)

    def update_switch(self, y, x=None, catch_up=True):
        if x is None:
            lst_px = self.last_lst_logpx
        else:
            lst_px = [cl(x) for cl in self.classifiers()]
        self.switch.Supdate(lst_px, y)

        if catch_up:
            self.hard_catch_up()

    def hard_catch_up(self, threshold=-20):
        logpost = self.switch.logposterior
        weak_cl = [cl for cl, lp in zip(self.classifiers(), logpost) if lp < threshold]
        if len(weak_cl) == 0:
            return None

        mean_weight = torch.stack(
            [cl.fc.weight * p for (cl, p) in zip(self.classifiers(), logpost.exp())],
            dim=-1).sum(dim=-1).detach()
        mean_bias = torch.stack(
            [cl.fc.bias * p for (cl, p) in zip(self.classifiers(), logpost.exp())],
            dim=-1).sum(dim=-1).detach()
        for cl in weak_cl:
            cl.fc.weight.data = mean_weight.clone()
            cl.fc.bias.data = mean_bias.clone()

    def parameters_model(self):
        return self.model.parameters()

    def classifiers(self):
        for i in range(self.nclassifiers):
            yield getattr(self, "classifier"+str(i))

    def classifiers_parameters_list(self):
        return [cl.parameters() for cl in self.classifiers()]

    def posterior(self):
        return self.switch.logposterior.exp()

    def classifiers_predictions(self, x=None):
        if x is None:
            return self.last_lst_logpx
        x = self.model(x)
        lst_px = [cl(x) for cl in self.classifiers()]
        self.last_lst_logpx = lst_px
        return lst_px

    def repr_posterior(self):
        post = self.posterior()
        bars = u' ▁▂▃▄▅▆▇█'
        res = "|"+"".join(bars[int(px)] for px in post/post.max() * 8) + "|"
        return res
