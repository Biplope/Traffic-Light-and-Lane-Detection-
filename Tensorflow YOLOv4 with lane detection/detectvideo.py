#!python detectvideo.py --weights yolov4-tiny-416 --size 416 --model yolov4 --video ./data/test-video2.mp4 --output vidout.avi --dis_cv2_window --tiny

import time
import tensorflow as tf
physical_devices = tf.config.experimental.list_physical_devices('GPU')
if len(physical_devices) > 0:
    tf.config.experimental.set_memory_growth(physical_devices[0], True)
from absl import app, flags, logging
from absl.flags import FLAGS
import core.utils as utils
from core.yolov4 import filter_boxes
from tensorflow.python.saved_model import tag_constants
from PIL import Image
import cv2
import numpy as np
from tensorflow.compat.v1 import ConfigProto
from tensorflow.compat.v1 import InteractiveSession

flags.DEFINE_string('framework', 'tf', '(tf, tflite, trt')
flags.DEFINE_string('weights', './checkpoints/yolov4-416',
                    'path to weights file')
flags.DEFINE_integer('size', 416, 'resize images to')
flags.DEFINE_boolean('tiny', False, 'yolo or yolo-tiny')
flags.DEFINE_string('model', 'yolov4', 'yolov3 or yolov4')
flags.DEFINE_string('video', './data/road.mp4', 'path to input video')
flags.DEFINE_float('iou', 0.45, 'iou threshold')
flags.DEFINE_float('score', 0.50, 'score threshold')
flags.DEFINE_string('output', None, 'path to output video')
flags.DEFINE_string('output_format', 'XVID', 'codec used in VideoWriter when saving video to file')
flags.DEFINE_boolean('dis_cv2_window', False, 'disable cv2 window during the process') # this is good for the .ipynb

def region_of_interest(img, vertices):
	mask = np.zeros_like(img)
	#channel_count = img.shape[2]
	match_mask_color = 255
	cv2.fillPoly(mask, vertices, match_mask_color)
	masked_image = cv2.bitwise_and(img, mask)
	return masked_image

def drow_the_lines(img, lines):
	img = np.copy(img)
	blank_image = np.zeros((img.shape[0], img.shape[1], 3), dtype=np.uint8)

	for line in lines:
		for x1, y1, x2, y2 in line:
			angle = int(np.arctan((y2-y1)/(x2-x1))*(180/3.14))
			if angle < 0:
				if not -85<angle<-35:
					continue 
			else:
				if not 35<angle<85:
					continue
			cv2.line(blank_image, (x1,y1), (x2,y2), (0, 255, 0), thickness=10)

	img = cv2.addWeighted(img, 0.8, blank_image, 1, 0.0)
	return img

def main(_argv):
    config = ConfigProto()
    config.gpu_options.allow_growth = True
    session = InteractiveSession(config=config)
    STRIDES, ANCHORS, NUM_CLASS, XYSCALE = utils.load_config(FLAGS)
    input_size = FLAGS.size
    video_path = FLAGS.video
    tot_frames = 0
    tot_time = 0

    print("Video from: ", video_path )
    vid = cv2.VideoCapture(video_path)

    if FLAGS.framework == 'tflite':
        interpreter = tf.lite.Interpreter(model_path=FLAGS.weights)
        interpreter.allocate_tensors()
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
        print(input_details)
        print(output_details)
    else:
        saved_model_loaded = tf.saved_model.load(FLAGS.weights, tags=[tag_constants.SERVING])
        infer = saved_model_loaded.signatures['serving_default']
    
    if FLAGS.output:
        # by default VideoCapture returns float instead of int
        width = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(vid.get(cv2.CAP_PROP_FPS))
        codec = cv2.VideoWriter_fourcc(*FLAGS.output_format)
        out = cv2.VideoWriter(FLAGS.output, codec, fps, (width, height))

    frame_id = 0
    while True:
        return_value, frame = vid.read()

        if frame is None:
          print("Done !!")
          break

        if return_value:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(frame)
        else:
            if frame_id == vid.get(cv2.CAP_PROP_FRAME_COUNT):
                print("Video processing complete")
                break
            raise ValueError("No image! Try with another video format")
        
        frame_size = frame.shape[:2]
        image_data = cv2.resize(frame, (input_size, input_size))
        image_data = image_data / 255.
        image_data = image_data[np.newaxis, ...].astype(np.float32)
        prev_time = time.time()

        if FLAGS.framework == 'tflite':
            interpreter.set_tensor(input_details[0]['index'], image_data)
            interpreter.invoke()
            pred = [interpreter.get_tensor(output_details[i]['index']) for i in range(len(output_details))]
            if FLAGS.model == 'yolov3' and FLAGS.tiny == True:
                boxes, pred_conf = filter_boxes(pred[1], pred[0], score_threshold=0.25,
                                                input_shape=tf.constant([input_size, input_size]))
            else:
                boxes, pred_conf = filter_boxes(pred[0], pred[1], score_threshold=0.25,
                                                input_shape=tf.constant([input_size, input_size]))
        else:
            batch_data = tf.constant(image_data)
            pred_bbox = infer(batch_data)
            for key, value in pred_bbox.items():
                boxes = value[:, :, 0:4]
                pred_conf = value[:, :, 4:]
        
        #print("Boxes: "+str(boxes))
        #print("Pred: "+str(pred_conf))
        #exit(0)

        boxes, scores, classes, valid_detections = tf.image.combined_non_max_suppression(
            boxes=tf.reshape(boxes, (tf.shape(boxes)[0], -1, 1, 4)),
            scores=tf.reshape(
                pred_conf, (tf.shape(pred_conf)[0], -1, tf.shape(pred_conf)[-1])),
            max_output_size_per_class=50,
            max_total_size=50,
            iou_threshold=FLAGS.iou,
            score_threshold=FLAGS.score
        )
        pred_bbox = [boxes.numpy(), scores.numpy(), classes.numpy(), valid_detections.numpy()]
        image,pred_names = utils.draw_bbox(frame, pred_bbox)
        print(" ")
        print(pred_names)

        result = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        height = frame.shape[0]
        width = frame.shape[1]
        region_of_interest_vertices = [
          (586,531),
          (930, 531),(1100,765)
          ,(150,765)
        ]

        gray_image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        canny_image = cv2.Canny(gray_image, 100,300)
        cropped_image = region_of_interest(canny_image,
              np.array([region_of_interest_vertices], np.int32),)
        lines = cv2.HoughLinesP(cropped_image,
                  rho=1,
                  theta=np.pi/180,
                  threshold=25,
                  lines=np.array([]),
                  minLineLength=4,
                  maxLineGap=750)
        image_with_lines = drow_the_lines(result, lines)

        curr_time = time.time()
        exec_time = curr_time - prev_time
        result = np.asarray(image)
        info = "time: %.2f ms" %(1000*exec_time)
        print(info)

        if not FLAGS.dis_cv2_window:
            cv2.namedWindow("result", cv2.WINDOW_AUTOSIZE)
            cv2.imshow("result", image_with_lines)
            if cv2.waitKey(1) & 0xFF == ord('q'): break

        tot_frames += 1
        tot_time += exec_time

        if FLAGS.output:
            out.write(image_with_lines)

        frame_id += 1

    print("Total frame: "+str(tot_frames))
    print("Total time: "+str(tot_time))
    print("Avg time: "+str(tot_time/tot_frames))

    #Total frame: 56
    #Avg time: 0.15030299765723093

if __name__ == '__main__':
    try:
        app.run(main)
    except SystemExit:
        pass
