# from __future__ import absolute_import
# from __future__ import division
# from __future__ import print_function

from datetime import datetime
from scipy import misc
import tensorflow as tf
import os
import src.facenet.detect_face
import cv2
import matplotlib.pyplot as plt
import math
import pickle
import dlib

# ============================================
# Global variables
# ============================================
IMAGE_PREFIX = 'img/FDDB-pics'
AVG_FACE_HEIGHT = 142.58539351061276
AVG_FACE_WIDTH = 94.11600875170973

gpu_memory_fraction = 1.0
minsize = 50 # minimum size of face
threshold = [0.6, 0.7, 0.7]  # three steps's threshold
factor = 0.709 # scale factor
face_cascade = cv2.CascadeClassifier('src/haarcascades/haarcascade_frontalface_default.xml')
dlib_face_detector = dlib.get_frontal_face_detector()


# ============================================
# Face detection methods
# ============================================

# Uses the HOG face detection algorithm internal in the dlib library
def hog_face_detect(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    rects = dlib_face_detector(gray, 1)
    return rects

# Acknowledgement: much of this code was taken from the blog of Charles Jekel, who explains
# how to use FaceNet to detect faces here: http://jekel.me/2017/How-to-detect-faces-using-facenet/
def cnn_face_detect(image):
    # Configuring facenet in facenet/src/compare.py
    with tf.Graph().as_default():
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=gpu_memory_fraction)
        sess = tf.Session(config=tf.ConfigProto(gpu_options=gpu_options, log_device_placement=False))
        with sess.as_default():
            pnet, rnet, onet = src.facenet.detect_face.create_mtcnn(sess, None)
        
        # run detect_face from the facenet library
        bounding_boxes, _ = src.facenet.detect_face.detect_face(image, minsize, pnet, rnet, onet, threshold, factor)

        # for each face detection, compute bounding box and add as tuple
        face_detections = []
        for (x1, y1, x2, y2, acc) in bounding_boxes:
            # skip detections with < 60% confidence
            if acc < .6:
                continue

            w = x2 - x1
            h = y2 - y1
            face_detections.append((x1, y1, w, h))
            
        return face_detections

def haar_face_detect(image, scaleFactor, minNeighbors, use_grayscale=True, cascade=None):
    # convert to grayscale if needed
    if use_grayscale:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    if not cascade:
        return face_cascade.detectMultiScale(image, scaleFactor, minNeighbors)
    else:
        return cascade.detectMultiScale(image, scaleFactor, minNeighbors)


# ============================================
# Helper functions
# ============================================

# for a given fold file that contains list of images in the fold,
# populates a list of all of the images in the fold and returns it
def get_image_list_from_file(file_name):
    image_list = []
    with open(file_name, 'r') as f:
        file_list = [x.rstrip() for x in f.readlines()]
        for file in file_list:
            img = cv2.imread('{}/{}.jpg'.format(IMAGE_PREFIX, file))
            image_list.append(img)
    return image_list

def get_image_list_from_file_misc(file_name):
    image_list = []
    with open(file_name, 'r') as f:
        file_list = [x.rstrip() for x in f.readlines()]
        for file in file_list:
            img = misc.imread('{}/{}.jpg'.format(IMAGE_PREFIX, file))
            image_list.append(img)
    return image_list

# From a given face label, which contains elliptical data:
# <major_axis_radius minor_axis_radius angle center_x center_y 1>,
# compute the bounding box for the face
def get_box_from_label(major, minor, angle, h, k):
    # lambda functions for computing x and y from parametric equiations for arbitrarily rotated ellipse
    comp_x = lambda t, h, a, b, phi: h + a*math.cos(t)*math.cos(phi) - b*math.sin(t)*math.sin(phi)
    comp_y = lambda t, k, a, b, phi: k + b*math.sin(t)*math.cos(phi) + a*math.cos(t)*math.sin(phi)

    # before any computation done, check if angle is 0
    if angle == 0:
        return (h - minor/2, k - major/2, minor, major)

    radians = (angle * math.pi) / 180

    
    # take gradient of ellipse equations with respect to t and set to 0. Yields
    # 0 = dx/dt = -a*sin(t)*cos(phi) - b*cos(t)*sin(phi)
    # 0 = dy/dt =  b*cos(t)*cos(phi) - a*sin(t)*sin(phi)
    # and then solve for t
    tan_t_x = -1 * minor * math.tan(radians) / major
    tan_t_y = minor * (1/math.tan(radians)) / major
    arctan_x = math.atan(tan_t_x)
    arctan_y = math.atan(tan_t_y)
    
    # compute left and right of bounding box
    x_min, x_max = comp_x(arctan_x, h, minor, major, radians), comp_x(arctan_x + math.pi, h, minor, major, radians)
    if x_max < x_min:
        x_min, x_max = x_max, x_min

    # compute top and bottom of bounding box
    y_min, y_max = comp_y(arctan_y, k, minor, major, radians), comp_y(arctan_y + math.pi, k, minor, major, radians)
    if y_max < y_min:
        y_min, y_max = y_max, y_min

    # return tuple (x_min, y_min, width, height)
    return (x_min, y_min, x_max - x_min, y_max - y_min)

# For a given fold number [1-10], retrieve a nested list of bounding boxes for faces for each image
# in the fold. Ex data: [[img1_face1, img1_face2], [img2_face1], ...] where each face bounding box
# is a tuple of (x, y, width, height)
def retrieve_face_list(fold_num):
    assert fold_num > 0 and fold_num <= 10

    fold_file = 'img/FDDB-folds/FDDB-fold-{:02}-ellipseList.txt'.format(fold_num)
    rectangle_file = 'img/FDDB-folds/FDDB-fold-{:02}-rectangleList.pkl'.format(fold_num)

    # If this list has already been created, can load it from a pickle file
    if os.path.exists(rectangle_file):
        print("loading from pickle")
        with open(rectangle_file, 'rb') as f:
            face_list = pickle.load(f)
    else:
        face_list = []
        count, face_count = 0, 0
        with open(fold_file, 'r') as f:
            file_name = f.readline().rstrip()
            while file_name:
                num_faces = int(f.readline().rstrip())
                count += 1
                face_count += num_faces
                
                # iterates over each of the faces in image
                faces = []
                for i in range(num_faces):
                    major, minor, angle, h, k, _ = map(float, f.readline().rstrip().split())
                    faces.append(get_box_from_label(major, minor, angle, h, k))
                face_list.append(faces)

                # go to next file
                file_name = f.readline().rstrip()

        print('num images: {}, total num faces: {}'.format(count, face_count))
        with open(rectangle_file, 'wb') as w:
            pickle.dump(face_list, w)

    return face_list

# ============================================
# Testing methods
# ============================================

def test_detection(fold_num, file_names, face_images, face_labels):
    total_faces, num_correct, false_pos = 0, 0, 0
    count = 0
    for image, label_set in zip(face_images, face_labels):
        file = file_names[count]
        count += 1
        # rows, cols, _ = image.shape
        
        # use predictor
        predictions = haar_face_detect(image, 1.2, 5)
        # predictions = cnn_face_detect(image)

        total_faces += len(label_set)
        faces_found_in_img = 0
        # for i in range(len(label_set)):
        for prediction in predictions:
            x_p, y_p, w_p, h_p = prediction
            center_px, center_py = x_p + w_p/2, y_p + h_p/2
            
            found_one = False
            for label in label_set:
                x_l, y_l, w_l, h_l = label
                center_lx, center_ly = x_l + w_l/2, y_l + h_l/2

                if (abs(center_lx - center_px) < .4*AVG_FACE_WIDTH and abs(center_ly - center_py) < .4*AVG_FACE_HEIGHT
                    and .5*w_l < w_p and w_p < 1.5*w_l and .5*h_l < h_p and h_p < 1.5*h_l):
                    # num_correct += 1
                    faces_found_in_img += 1
                    found_one = True
                    break

            if found_one is False:
                false_pos += 1

        # in case faces are somehow really close together and overflow? shouldnt be possible now
        if faces_found_in_img > len(predictions):
            faces_found_in_img = len(predictions)

        num_correct += faces_found_in_img

        # print('found {} of {} faces in this image'.format(faces_found_in_img, len(label_set)))


    print("found {} out of {} faces in ".format(num_correct, total_faces))
    print("accuracy: {}".format(num_correct/total_faces))
    return num_correct, total_faces, false_pos

def test_on_one_image(file_names, face_labels):
    name = '2002/08/05/big/img_3666'
    img = cv2.imread('img/FDDB-pics/{}.jpg'.format(name))

    index = -1
    for i, file in enumerate(file_names):
        if name in file:
            index = i
            break

    print('found file at index {}'.format(i))

    # faces = cnn_face_detect(img)
    faces = haar_face_detect(img, 1.3, 5)
    print("detections: (x,y,w,h)")
    for (x,y,w,h) in faces:
        print(x,y,w,h)
        cv2.rectangle(img,(int(x),int(y)),(int(x+w),int(y+h)),(255,0,0),2)

    print('labels:')
    print(face_labels[i])


    plt.figure()
    plt.imshow(img)
    plt.show()


    # file name: 2002/08/19/big/img_353
    # found 5 of 5 faces in this image
    # image num: 124
    # file name: 2002/08/19/big/img_350
    # found 0 of 5 faces in this image
    # image num: 125
    # file name: 2002/08/05/big/img_3392
    # found 0 of 4 faces in this image


# The main method is used to compare the accuracies of the FaceNet detector and Haar Cascade detector
# 
def main():
    total_correct, total_faces, total_false_pos = 0, 0, 0
    start_time = datetime.now()
    for fold_num in [2,3,4,5]:
        img_list_file = 'img/FDDB-folds/FDDB-fold-{:02}.txt'.format(fold_num)
        face_images = get_image_list_from_file(img_list_file)
        face_labels = retrieve_face_list(fold_num)
        # misc_face_images = get_image_list_from_file_misc(img_list_file)

        with open(img_list_file, 'r') as f:
            file_names = [x.rstrip() for x in f.readlines()]
        # num_correct, num_faces = test_detection(fold_num, file_names, misc_face_images, face_labels)
        num_correct, num_faces, false_pos = test_detection(fold_num, file_names, face_images, face_labels)

        total_correct += num_correct
        total_faces += num_faces
        total_false_pos += false_pos

    delta = datetime.now() - start_time
    print('******** TOTALS ***********')
    print('found {}/{} faces'.format(total_correct, total_faces))
    print('num false pos: {}'.format(false_pos))
    print('accuracy: {}'.format(total_correct/total_faces))
    print('Time elapsed (hh:mm:ss.ms) {}'.format(delta))

def test_one_image():
    # test_on_one_image(file_names, face_labels)
    pass




if __name__ == "__main__":
    main()
