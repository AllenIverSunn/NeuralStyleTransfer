import os
import sys
import numpy as np
import scipy.io
import scipy.misc
import tensorflow as tf
import cv2
import matplotlib.image as mpimg
import cv2


# 输出文件夹
OUTPUT_DIR = 'hfut/'
# 风格图像位置
STYLE_IMAGE = './imgs/5.jpg'
# 内容图像位置
CONTENT_IMAGE = './imgs/hfut.jpg'
# 图像的大小
IMAGE_WIDTH = 220
IMAGE_HEIGHT = 273
COLOR_CHANNELS = 3


# 设置随机噪声图像与内容图像的比率
NOISE_RATIO = 0.6
# 设置迭代次数
ITERATIONS = 1000
# 设置内容图像与风格图像的权重
alpha = 1
beta = 200
# 加载VGG-19 MODEL及设定均值
VGG_Model = './imagenet-vgg-verydeep-19.mat'
MEAN_VALUES = np.array([123.68, 116.779, 103.939]).reshape((1, 1, 1, 3))
# 设置需要用到的卷积层
CONTENT_LAYERS = [('conv4_2', 1.)]
STYLE_LAYERS = [('conv1_1', 0.2), ('conv2_1', 0.2), ('conv3_1', 0.2), ('conv4_1', 0.2), ('conv5_1', 0.2)]


# 生成随机噪声图，与content图以一定比率融合
def generate_noise_image(content_image, noise_ratio = NOISE_RATIO):
    noise_image = np.random.uniform(
            -20, 20,
            (1, IMAGE_HEIGHT, IMAGE_WIDTH, COLOR_CHANNELS)).astype('float32')
    img = noise_image * noise_ratio + content_image * (1 - noise_ratio)
    return img


def load_image(path):
    image = cv2.imread(path)
    # 由于pytorch的conv层要求为四个维度(batch, height, width, channels)，所以此处增加一个维度
    image = cv2.resize(image,(220,273), interpolation=cv2.INTER_CUBIC)
    image = np.reshape(image, ((1,) + image.shape))
    # 减去均值
    image = image - MEAN_VALUES
    return image


def save_image(path, image):
    # 输出要加上均值
    image = image + MEAN_VALUES
    # 去掉第一个维度
    image = image[0]
    image = np.clip(image, 0, 255).astype('uint8')
    cv2.imwrite(path, image)


def build_net(ntype, nin, nwb=None):
    print(nin)
    if ntype == 'conv':
        return tf.nn.relu(tf.nn.conv2d(nin, nwb[0], strides=[1, 1, 1, 1], padding='SAME') + nwb[1])
    elif ntype == 'pool':
        return tf.nn.avg_pool(nin, ksize=[1, 2, 2, 1],
                              strides=[1, 2, 2, 1], padding='SAME')


def get_weight_bias(vgg_layers, i):
    weights, bias = vgg_layers[i][0][0][0][0]
    # weights = vgg_layers[i][0][0][2][0][0]
    weights = tf.constant(weights)
    # bias = vgg_layers[i][0][0][2][0][1]
    bias = tf.constant(np.reshape(bias, (bias.size)))
    return weights, bias


# 读入VGG19
def build_vgg19(path):
    net = {}
    vgg_rawnet = scipy.io.loadmat(path)
    vgg_layers = vgg_rawnet['layers'][0]
    a = np.zeros((1, IMAGE_HEIGHT, IMAGE_WIDTH, 3)).astype('float32')
    print(a.shape, a.dtype)
    net['input'] = tf.Variable(np.zeros((1, IMAGE_HEIGHT, IMAGE_WIDTH, 3)).astype('float32'))
    net['conv1_1'] = build_net('conv', net['input'], get_weight_bias(vgg_layers, 0))
    net['conv1_2'] = build_net('conv', net['conv1_1'], get_weight_bias(vgg_layers, 2))
    net['pool1'] = build_net('pool', net['conv1_2'])
    net['conv2_1'] = build_net('conv', net['pool1'], get_weight_bias(vgg_layers, 5))
    net['conv2_2'] = build_net('conv', net['conv2_1'], get_weight_bias(vgg_layers, 7))
    net['pool2'] = build_net('pool', net['conv2_2'])
    net['conv3_1'] = build_net('conv', net['pool2'], get_weight_bias(vgg_layers, 10))
    net['conv3_2'] = build_net('conv', net['conv3_1'], get_weight_bias(vgg_layers, 12))
    net['conv3_3'] = build_net('conv', net['conv3_2'], get_weight_bias(vgg_layers, 14))
    net['conv3_4'] = build_net('conv', net['conv3_3'], get_weight_bias(vgg_layers, 16))
    net['pool3'] = build_net('pool', net['conv3_4'])
    net['conv4_1'] = build_net('conv', net['pool3'], get_weight_bias(vgg_layers, 19))
    net['conv4_2'] = build_net('conv', net['conv4_1'], get_weight_bias(vgg_layers, 21))
    net['conv4_3'] = build_net('conv', net['conv4_2'], get_weight_bias(vgg_layers, 23))
    net['conv4_4'] = build_net('conv', net['conv4_3'], get_weight_bias(vgg_layers, 25))
    net['pool4'] = build_net('pool', net['conv4_4'])
    net['conv5_1'] = build_net('conv', net['pool4'], get_weight_bias(vgg_layers, 28))
    net['conv5_2'] = build_net('conv', net['conv5_1'], get_weight_bias(vgg_layers, 30))
    net['conv5_3'] = build_net('conv', net['conv5_2'], get_weight_bias(vgg_layers, 32))
    net['conv5_4'] = build_net('conv', net['conv5_3'], get_weight_bias(vgg_layers, 34))
    net['pool5'] = build_net('pool', net['conv5_4'])
    return net


def content_layer_loss(p, x):
    M = p.shape[1] * p.shape[2]
    N = p.shape[3]
    loss = (1. / (2 * N * M)) * tf.reduce_sum(tf.pow((x - p), 2))
    return loss


def content_loss_func(sess, net):
    layers = CONTENT_LAYERS
    total_content_loss = 0.0
    for layer_name, weight in layers:
        p = sess.run(net[layer_name])
        x = net[layer_name]
        print(p == x)
        print(p.shape, x.shape)
        print(type(p), type(x))
        total_content_loss += content_layer_loss(p, x)*weight

    total_content_loss /= float(len(layers))
    return total_content_loss


def gram_matrix(x, area, depth):

    x1 = tf.reshape(x, (area, depth))
    g = tf.matmul(tf.transpose(x1), x1)
    return g


def style_layer_loss(a, x):
    M = a.shape[1] * a.shape[2]
    N = a.shape[3]
    A = gram_matrix(a, M, N)
    G = gram_matrix(x, M, N)
    loss = (1. / (4 * N ** 2 * M ** 2)) * tf.reduce_sum(tf.pow((G - A), 2))
    return loss


def style_loss_func(sess, net):
    layers = STYLE_LAYERS
    total_style_loss = 0.0
    for layer_name, weight in layers:
        a = sess.run(net[layer_name])
        x = net[layer_name]
        total_style_loss += style_layer_loss(a, x) * weight
    total_style_loss /= float(len(layers))
    return total_style_loss


def main():
    net = build_vgg19(VGG_Model)
    sess = tf.Session()
    sess.run(tf.initialize_all_variables())

    content_img = load_image(CONTENT_IMAGE)
    style_img = load_image(STYLE_IMAGE)

    sess.run([net['input'].assign(content_img)])
    cost_content = content_loss_func(sess, net)

    sess.run([net['input'].assign(style_img)])
    cost_style = style_loss_func(sess, net)

    total_loss = alpha * cost_content + beta * cost_style
    optimizer = tf.train.AdamOptimizer(2.0)

    init_img = generate_noise_image(content_img)

    train_op = optimizer.minimize(total_loss)
    sess.run(tf.initialize_all_variables())
    sess.run(net['input'].assign(init_img))

    for it in range(ITERATIONS):
        print(it)
        sess.run(train_op)
        if it % 10 == 0:
            mixed_image = sess.run(net['input'])
            print('Iteration %d' % (it))
            print('sum : ', sess.run(tf.reduce_sum(mixed_image)))
            print('cost: ', sess.run(total_loss))

            if not os.path.exists(OUTPUT_DIR):
                os.mkdir(OUTPUT_DIR)

            filename = 'result/%d.jpg' % (it)
            save_image(filename, mixed_image)

if __name__ == '__main__':
    main()
